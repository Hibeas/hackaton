"""Ring buffer of corridor delay samples for short-term (10-30 min) forecasting."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from aiokafka import AIOKafkaConsumer

from corridor_service import _event_in_corridor, load_corridor_config

logger = logging.getLogger(__name__)

KAFKA_BOOTSTRAP_SERVERS = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:8081")
KAFKA_TOPIC = os.environ.get("KAFKA_TOPIC", "port-traffic-events")
KAFKA_CONSUMER_GROUP = os.environ.get("KAFKA_CONSUMER_GROUP", "port-ai-forecast")
KAFKA_CONSUMER_ENABLED = os.environ.get("KAFKA_CONSUMER_ENABLED", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
BUFFER_MINUTES = int(os.environ.get("KAFKA_PREDICTION_BUFFER_MINUTES", "30"))
MIN_SAMPLES_SHORT = int(os.environ.get("KAFKA_PREDICTION_MIN_SAMPLES", "3"))


@dataclass
class DelaySample:
    corridor_id: str
    port_id: str
    delay_sec: float
    observed_at: datetime


class KafkaPredictionBuffer:
    def __init__(self, retention_minutes: int = BUFFER_MINUTES) -> None:
        self.retention_minutes = retention_minutes
        self._samples: dict[str, deque[DelaySample]] = defaultdict(deque)
        self._corridor_index: list[dict[str, Any]] = []
        self._index_loaded_at: datetime | None = None
        self.messages_ingested = 0

    def _ensure_corridor_index(self) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        if self._index_loaded_at and (now - self._index_loaded_at).total_seconds() < 300:
            return self._corridor_index
        config = load_corridor_config()
        indexed: list[dict[str, Any]] = []
        for port in config.get("ports") or []:
            for corridor in port.get("corridors") or []:
                indexed.append(
                    {
                        "corridor_id": corridor["id"],
                        "port_id": port["id"],
                        "bbox": corridor["bbox"],
                        "polygon": corridor.get("polygon"),
                    }
                )
        self._corridor_index = indexed
        self._index_loaded_at = now
        return indexed

    def _prune(self, corridor_id: str) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=self.retention_minutes)
        queue = self._samples[corridor_id]
        while queue and queue[0].observed_at < cutoff:
            queue.popleft()

    def ingest_snapshot(self, snapshot: dict[str, Any]) -> None:
        corridor_id = snapshot.get("corridor_id")
        if not corridor_id:
            return
        metrics = snapshot.get("metrics") or {}
        delay = float(metrics.get("total_delay_sec") or metrics.get("max_delay_sec") or 0)
        observed_raw = snapshot.get("timestamp")
        try:
            observed_at = (
                datetime.fromisoformat(str(observed_raw).replace("Z", "+00:00"))
                if observed_raw
                else datetime.now(timezone.utc)
            )
        except ValueError:
            observed_at = datetime.now(timezone.utc)
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=timezone.utc)

        self._samples[corridor_id].append(
            DelaySample(
                corridor_id=corridor_id,
                port_id=str(snapshot.get("port_id") or ""),
                delay_sec=delay,
                observed_at=observed_at,
            )
        )
        self._prune(corridor_id)
        self.messages_ingested += 1

    def ingest_event(self, event: dict[str, Any]) -> None:
        if event.get("record_kind") == "corridor_snapshot":
            self.ingest_snapshot(event)
            return

        location = event.get("location") or {}
        lat = location.get("lat")
        lon = location.get("lon")
        if lat is None or lon is None:
            return
        metrics = event.get("metrics") or {}
        delay = metrics.get("delay_sec")
        if delay is None:
            return

        observed_raw = event.get("timestamp")
        try:
            observed_at = (
                datetime.fromisoformat(str(observed_raw).replace("Z", "+00:00"))
                if observed_raw
                else datetime.now(timezone.utc)
            )
        except ValueError:
            observed_at = datetime.now(timezone.utc)
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=timezone.utc)

        for entry in self._ensure_corridor_index():
            if _event_in_corridor(event, entry):
                self._samples[entry["corridor_id"]].append(
                    DelaySample(
                        corridor_id=entry["corridor_id"],
                        port_id=entry["port_id"],
                        delay_sec=float(delay),
                        observed_at=observed_at,
                    )
                )
                self._prune(entry["corridor_id"])
                self.messages_ingested += 1

    def ingest_kafka_payload(self, payload: dict[str, Any]) -> None:
        self.ingest_event(payload)

    def extrapolate_delay(
        self,
        corridor_id: str,
        horizon_minutes: int,
    ) -> dict[str, Any] | None:
        self._prune(corridor_id)
        queue = self._samples.get(corridor_id)
        if not queue or len(queue) < MIN_SAMPLES_SHORT:
            return None

        now = datetime.now(timezone.utc)
        points: list[tuple[float, float]] = []
        for sample in queue:
            age_min = (now - sample.observed_at).total_seconds() / 60.0
            points.append((age_min, sample.delay_sec))

        if len(points) < 2:
            predicted = points[-1][1]
        else:
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            n = len(xs)
            mean_x = sum(xs) / n
            mean_y = sum(ys) / n
            denom = sum((x - mean_x) ** 2 for x in xs)
            if denom <= 1e-9:
                slope = 0.0
            else:
                slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denom
            current_delay = ys[-1]
            predicted = current_delay + slope * horizon_minutes

        predicted = max(0.0, min(3600.0, predicted))
        port_id = queue[-1].port_id
        confidence = "high" if len(queue) >= 8 else "medium"
        return {
            "corridor_id": corridor_id,
            "port_id": port_id,
            "horizon_minutes": horizon_minutes,
            "predicted_delay_sec": int(round(predicted)),
            "method": "kafka_trend",
            "confidence": confidence,
            "samples_in_buffer": len(queue),
        }

    def status(self) -> dict[str, Any]:
        total = sum(len(q) for q in self._samples.values())
        return {
            "retention_minutes": self.retention_minutes,
            "corridors_tracked": len(self._samples),
            "samples_total": total,
            "messages_ingested": self.messages_ingested,
        }


kafka_prediction_buffer = KafkaPredictionBuffer()


async def kafka_consumer_loop() -> None:
    if not KAFKA_CONSUMER_ENABLED:
        logger.info("Kafka prediction consumer disabled")
        return

    consumer = AIOKafkaConsumer(
        KAFKA_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        group_id=KAFKA_CONSUMER_GROUP,
        enable_auto_commit=True,
        auto_offset_reset="latest",
        value_deserializer=lambda value: json.loads(value.decode("utf-8")),
    )
    try:
        await consumer.start()
        logger.info(
            "Kafka prediction consumer started (topic=%s, group=%s)",
            KAFKA_TOPIC,
            KAFKA_CONSUMER_GROUP,
        )
        async for message in consumer:
            try:
                payload = message.value
                if isinstance(payload, dict):
                    kafka_prediction_buffer.ingest_kafka_payload(payload)
            except Exception as exc:
                logger.warning("Kafka message ingest failed: %s", exc)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning("Kafka prediction consumer stopped: %s", exc)
    finally:
        try:
            await consumer.stop()
        except Exception:
            pass
