"""Hybrid delay forecast: 10-30 min from Kafka buffer, >30 min from ML model."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from corridor_service import load_corridor_config
from kafka_prediction_buffer import KafkaPredictionBuffer, kafka_prediction_buffer
from observation_store import ObservationStore
from traffic_ml_predictor import predict_corridor_long_term

DEFAULT_HORIZONS = (10, 15, 20, 30, 45, 60, 120, 180)
SHORT_TERM_MAX_MINUTES = 30
ML_ONLY_MIN_HORIZON = SHORT_TERM_MAX_MINUTES + 1


def _forecast_from_observation_store(
    store: ObservationStore,
    corridor_id: str,
    port_id: str,
    horizon_minutes: int,
    reference: datetime | None = None,
) -> dict[str, Any] | None:
    history = store.get_history(corridor_id, minutes=30, reference=reference)
    if len(history) < 2:
        return None

    delays: list[float] = []
    for item in history:
        metrics = item.get("metrics") or {}
        delays.append(float(metrics.get("total_delay_sec") or 0))

    if len(delays) < 2:
        return None

    slope = (delays[-1] - delays[0]) / max(1, len(delays) - 1)
    predicted = max(0.0, min(3600.0, delays[-1] + slope * horizon_minutes))
    return {
        "corridor_id": corridor_id,
        "port_id": port_id,
        "horizon_minutes": horizon_minutes,
        "predicted_delay_sec": int(round(predicted)),
        "method": "observation_trend",
        "confidence": "low",
        "samples_in_buffer": len(history),
    }


def build_corridor_forecasts(
    *,
    buffer: KafkaPredictionBuffer | None = None,
    observation_store: ObservationStore | None = None,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    port_id: str | None = None,
    corridor_id: str | None = None,
    reference: datetime | None = None,
) -> list[dict[str, Any]]:
    buf = buffer or kafka_prediction_buffer
    store = observation_store
    config = load_corridor_config()
    now = reference or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    forecasts: list[dict[str, Any]] = []

    for port in config.get("ports") or []:
        if port_id and port.get("id") != port_id:
            continue
        for corridor in port.get("corridors") or []:
            cid = corridor["id"]
            if corridor_id and cid != corridor_id:
                continue
            pid = port["id"]

            for horizon in horizons:
                item: dict[str, Any] | None = None
                if horizon < ML_ONLY_MIN_HORIZON:
                    item = buf.extrapolate_delay(cid, horizon, reference=now)
                    if item is None and store is not None:
                        item = _forecast_from_observation_store(
                            store, cid, pid, horizon, reference=now
                        )
                else:
                    ml_item = predict_corridor_long_term(
                        corridor,
                        horizon_minutes=horizon,
                        reference=now,
                    )
                    if ml_item:
                        item = {
                            **ml_item,
                            "port_id": pid,
                            "corridor_name": corridor.get("name"),
                        }

                if item:
                    item.setdefault("port_id", pid)
                    item.setdefault("corridor_name", corridor.get("name"))
                    forecasts.append(item)

    forecasts.sort(
        key=lambda row: (row.get("port_id", ""), row.get("corridor_id", ""), row.get("horizon_minutes", 0))
    )
    return forecasts


def build_forecast_response(
    *,
    buffer: KafkaPredictionBuffer | None = None,
    observation_store: ObservationStore | None = None,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    port_id: str | None = None,
    corridor_id: str | None = None,
) -> dict[str, Any]:
    buf = buffer or kafka_prediction_buffer
    forecasts = build_corridor_forecasts(
        buffer=buf,
        observation_store=observation_store,
        horizons=horizons,
        port_id=port_id,
        corridor_id=corridor_id,
    )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "horizons": list(horizons),
        "short_term_max_minutes": SHORT_TERM_MAX_MINUTES,
        "forecasts": forecasts,
        "kafka_buffer": buf.status(),
        "ml_enabled": any(item.get("method") == "ml_historical" for item in forecasts),
    }
