"""Rolling in-memory traffic history for bottleneck and trend analysis."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

HISTORY_MAX_SAMPLES = 120
SAMPLE_INTERVAL_SECONDS = 30.0


@dataclass
class HistoryPoint:
    timestamp: datetime
    status: str
    intensity_vph: float | None = None
    speed_kmh: float | None = None
    delay_sec: int | None = None
    magnitude: int | None = None
    city: str | None = None
    road_name: str | None = None
    source_type: str | None = None
    record_kind: str | None = None


@dataclass
class EntityHistory:
    entity_id: str
    event_id: str
    points: deque[HistoryPoint] = field(default_factory=lambda: deque(maxlen=HISTORY_MAX_SAMPLES))
    max_delay_sec: int = 0
    critical_samples: int = 0
    congestion_samples: int = 0

    def record(self, point: HistoryPoint) -> None:
        self.points.append(point)
        if point.delay_sec is not None:
            self.max_delay_sec = max(self.max_delay_sec, point.delay_sec)
        if point.status == "CRITICAL":
            self.critical_samples += 1
        elif point.status == "CONGESTION":
            self.congestion_samples += 1

    def latest(self) -> HistoryPoint | None:
        return self.points[-1] if self.points else None

    def points_in_window(self, window: timedelta) -> list[HistoryPoint]:
        if not self.points:
            return []
        cutoff = self.points[-1].timestamp - window
        return [p for p in self.points if p.timestamp >= cutoff]

    def bottleneck_score(self, window: timedelta) -> float:
        window_points = self.points_in_window(window)
        if not window_points:
            return 0.0
        critical = sum(1 for p in window_points if p.status == "CRITICAL")
        congestion = sum(1 for p in window_points if p.status == "CONGESTION")
        max_delay = max((p.delay_sec or 0) for p in window_points)
        return (critical * 3.0 + congestion * 1.0) * SAMPLE_INTERVAL_SECONDS / 60.0 + max_delay / 60.0

    def intensity_trend_pct(self, window_minutes: int = 15) -> float | None:
        window = timedelta(minutes=window_minutes)
        points = [
            p for p in self.points_in_window(window) if p.intensity_vph is not None
        ]
        if len(points) < 4:
            return None
        first_half = points[: len(points) // 2]
        second_half = points[len(points) // 2 :]
        avg_first = sum(float(p.intensity_vph) for p in first_half) / len(first_half)  # type: ignore[arg-type]
        avg_second = sum(float(p.intensity_vph) for p in second_half) / len(second_half)  # type: ignore[arg-type]
        if avg_first <= 0:
            return None
        return ((avg_second - avg_first) / avg_first) * 100.0


class TrafficHistory:
    def __init__(self) -> None:
        self._entities: dict[str, EntityHistory] = {}
        self._seen_tomtom_present: set[str] = set()
        self._last_snapshot_at: datetime | None = None

    @property
    def last_snapshot_at(self) -> datetime | None:
        return self._last_snapshot_at

    def entity_key(self, event: dict[str, Any]) -> str:
        return str(event.get("entity_id") or event.get("event_id") or "unknown")

    def record_snapshot(self, events: list[dict[str, Any]], *, now: datetime | None = None) -> None:
        ts = now or datetime.now(timezone.utc)
        current_tomtom_present: set[str] = set()

        for event in events:
            entity_id = self.entity_key(event)
            metrics = event.get("metrics") or {}
            location = event.get("location") or {}
            point = HistoryPoint(
                timestamp=ts,
                status=str(event.get("status") or "CLEAR"),
                intensity_vph=metrics.get("intensity_vph"),
                speed_kmh=metrics.get("speed_kmh"),
                delay_sec=metrics.get("delay_sec"),
                magnitude=metrics.get("magnitude"),
                city=event.get("city"),
                road_name=location.get("road_name"),
                source_type=event.get("source_type"),
                record_kind=event.get("record_kind"),
            )

            if entity_id not in self._entities:
                self._entities[entity_id] = EntityHistory(
                    entity_id=entity_id,
                    event_id=str(event.get("event_id") or entity_id),
                )
            self._entities[entity_id].record(point)

            if (
                event.get("source_type") == "tomtom_traffic"
                and (event.get("context") or {}).get("time_validity") == "present"
            ):
                current_tomtom_present.add(entity_id)

        self._seen_tomtom_present = current_tomtom_present
        self._last_snapshot_at = ts
        self._prune_stale(ts)

    def _prune_stale(self, now: datetime) -> None:
        cutoff = now - timedelta(hours=2)
        stale = [
            key
            for key, entity in self._entities.items()
            if entity.latest() is not None and entity.latest().timestamp < cutoff  # type: ignore[union-attr]
        ]
        for key in stale:
            del self._entities[key]

    def get_entity(self, entity_id: str) -> EntityHistory | None:
        return self._entities.get(entity_id)

    def all_entities(self) -> list[EntityHistory]:
        return list(self._entities.values())

    def seen_tomtom_present_ids(self) -> set[str]:
        return set(self._seen_tomtom_present)

    def rank_bottlenecks(
        self,
        *,
        window_minutes: int = 60,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        window = timedelta(minutes=window_minutes)
        ranked: list[tuple[float, EntityHistory]] = []
        for entity in self._entities.values():
            score = entity.bottleneck_score(window)
            if score <= 0:
                continue
            ranked.append((score, entity))
        ranked.sort(key=lambda item: item[0], reverse=True)

        results: list[dict[str, Any]] = []
        for score, entity in ranked[:limit]:
            latest = entity.latest()
            if latest is None:
                continue
            results.append(
                {
                    "entity_id": entity.entity_id,
                    "event_id": entity.event_id,
                    "score": round(score, 2),
                    "city": latest.city,
                    "location": latest.road_name or entity.entity_id,
                    "status": latest.status,
                    "source_type": latest.source_type,
                    "record_kind": latest.record_kind,
                    "max_delay_sec": entity.max_delay_sec,
                    "critical_samples": entity.critical_samples,
                    "congestion_samples": entity.congestion_samples,
                    "window_minutes": window_minutes,
                }
            )
        return results
