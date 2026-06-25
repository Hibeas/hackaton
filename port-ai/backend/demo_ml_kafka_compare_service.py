"""Compare kafka_trend vs ml_historical after synthetic spike injection."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from corridor_service import find_corridor_by_id
from demo_baltic_spike_service import resolve_corridor_context
from demo_crowd_scenario_service import inject_crowd_scenario
from demo_random_corridor import pick_random_approach_corridor
from hybrid_delay_forecaster import DEFAULT_HORIZONS, build_corridor_forecasts
from kafka_prediction_buffer import kafka_prediction_buffer
from operational_action_service import build_operational_actions, compute_operational_importance
from slot_recommendation_service import recommend_slots_for_corridor
from synthetic_crowd_map import build_crowd_map_payload
from traffic_ml_predictor import predict_corridor_long_term

COMPARE_HORIZONS = (10, 15, 20, 30, 45, 60, 120)
DIVERGENCE_THRESHOLD_PCT = float(os.environ.get("DEMO_ML_KAFKA_DIVERGENCE_PCT", "25"))
PULSE_MIN_DELAY_SEC = 480

INCIDENT_CAUSE = (
    "[TEST ML vs Kafka] Sztuczny spike — porównanie kafka_trend (live) z ml_historical (baseline)."
)


def _forecast_side_by_side(
    *,
    corridor: dict[str, Any],
    corridor_id: str,
    port_id: str,
    reference: datetime,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for horizon in COMPARE_HORIZONS:
        kafka_item = kafka_prediction_buffer.extrapolate_delay(
            corridor_id,
            horizon,
            reference=reference,
        )
        ml_item = predict_corridor_long_term(
            corridor,
            horizon_minutes=horizon,
            reference=reference,
        )
        kafka_sec = int(kafka_item["predicted_delay_sec"]) if kafka_item else None
        ml_sec = int(ml_item["predicted_delay_sec"]) if ml_item else None
        divergence_pct: float | None = None
        diverged = False
        if kafka_sec is not None and ml_sec is not None:
            base = max(kafka_sec, ml_sec, 1)
            divergence_pct = round(abs(kafka_sec - ml_sec) / base * 100.0, 1)
            diverged = divergence_pct > DIVERGENCE_THRESHOLD_PCT
        rows.append(
            {
                "horizon_minutes": horizon,
                "kafka_trend_sec": kafka_sec,
                "ml_historical_sec": ml_sec,
                "kafka_available": kafka_item is not None,
                "ml_available": ml_item is not None,
                "divergence_pct": divergence_pct,
                "diverged": diverged,
                "divergence_expected": bool(
                    diverged
                    and kafka_sec is not None
                    and kafka_sec >= PULSE_MIN_DELAY_SEC
                    and ml_sec is not None
                ),
                "kafka_confidence": (kafka_item or {}).get("confidence"),
                "ml_confidence": (ml_item or {}).get("confidence"),
            }
        )
    return rows


def build_method_comparison_validation(
    *,
    comparisons: list[dict[str, Any]],
    inject_meta: dict[str, Any],
    hybrid_forecasts: list[dict[str, Any]],
) -> dict[str, Any]:
    kafka_at_30_row = next(
        (row for row in comparisons if row["horizon_minutes"] == 30),
        None,
    )
    kafka_at_30 = int(kafka_at_30_row["kafka_trend_sec"] or 0) if kafka_at_30_row else 0
    kafka_short_max = max(
        (int(row.get("kafka_trend_sec") or 0) for row in comparisons if int(row.get("horizon_minutes") or 0) <= 30),
        default=kafka_at_30,
    )
    comparable = [row for row in comparisons if row.get("divergence_pct") is not None]
    diverged_rows = [row for row in comparable if row.get("diverged")]
    ml_rows = [row for row in comparisons if row.get("ml_historical_sec") is not None]
    hybrid_30 = next(
        (item for item in hybrid_forecasts if int(item.get("horizon_minutes") or 0) == 30),
        None,
    )
    hybrid_60 = next(
        (item for item in hybrid_forecasts if int(item.get("horizon_minutes") or 0) == 60),
        None,
    )

    checks = [
        {
            "id": "samples_injected",
            "label": "Kafka + obserwacje",
            "ok": int(inject_meta.get("samples_injected") or 0) >= 4,
            "detail": f"{inject_meta.get('samples_injected', 0)} próbek",
        },
        {
            "id": "kafka_elevated_short",
            "label": "kafka_trend podniesiony (horyzont ≤30 min)",
            "ok": kafka_short_max >= PULSE_MIN_DELAY_SEC,
            "detail": f"max krótki {kafka_short_max}s ({kafka_short_max // 60} min), 30 min: {kafka_at_30}s",
        },
        {
            "id": "ml_forecasts",
            "label": "ml_historical dostępny",
            "ok": len(ml_rows) >= 3,
            "detail": f"{len(ml_rows)} horyzontów ML",
        },
        {
            "id": "hybrid_short_kafka",
            "label": "Hybrid ≤30 min → kafka_trend",
            "ok": str((hybrid_30 or {}).get("method") or "") == "kafka_trend",
            "detail": str((hybrid_30 or {}).get("method") or "brak"),
        },
        {
            "id": "hybrid_long_ml",
            "label": "Hybrid ≥45 min → ml_historical",
            "ok": str((hybrid_60 or {}).get("method") or "") == "ml_historical",
            "detail": str((hybrid_60 or {}).get("method") or "brak"),
        },
        {
            "id": "divergence_detected",
            "label": f"Rozjazd >{DIVERGENCE_THRESHOLD_PCT:.0f}% (oczekiwany po spike)",
            "ok": len(diverged_rows) >= 1,
            "detail": f"{len(diverged_rows)} horyzontów z rozjazdem",
        },
    ]

    return {
        "passed": all(item["ok"] for item in checks),
        "checks": checks,
        "comparisons": comparisons,
        "divergence_threshold_pct": DIVERGENCE_THRESHOLD_PCT,
        "diverged_horizons": [row["horizon_minutes"] for row in diverged_rows],
        "kafka_at_horizon_30_sec": kafka_at_30,
        "comparable_count": len(comparable),
    }


def run_ml_kafka_compare_demo(
    *,
    observation_store: Any,
    port_id: str | None = None,
    corridor_id: str | None = None,
    peak_delay_sec: int = 960,
    mark_slots_at_risk: bool = False,
) -> dict[str, Any]:
    if corridor_id:
        picked = {"corridor_id": corridor_id.strip(), "port_id": port_id}
        context = resolve_corridor_context(corridor_id.strip())
    else:
        picked = pick_random_approach_corridor(port_id=port_id)
        corridor_id = picked["corridor_id"]
        context = resolve_corridor_context(corridor_id)

    _port, corridor = find_corridor_by_id(corridor_id)
    now = datetime.now(timezone.utc)

    inject_meta = inject_crowd_scenario(
        corridor_id=corridor_id,
        observation_store=observation_store,
        peak_delay_sec=peak_delay_sec,
        incident_cause=INCIDENT_CAUSE,
    )

    comparisons = _forecast_side_by_side(
        corridor=corridor,
        corridor_id=corridor_id,
        port_id=context["port_id"],
        reference=now,
    )

    hybrid_forecasts = build_corridor_forecasts(
        buffer=kafka_prediction_buffer,
        observation_store=observation_store,
        horizons=DEFAULT_HORIZONS,
        corridor_id=corridor_id,
        reference=now,
    )
    corridor_forecasts = [item for item in hybrid_forecasts if item.get("corridor_id") == corridor_id]

    horizon_item = next(
        (item for item in corridor_forecasts if int(item.get("horizon_minutes") or 0) == 30),
        corridor_forecasts[0] if corridor_forecasts else None,
    )
    horizon_minutes = int((horizon_item or {}).get("horizon_minutes") or 30)
    predicted = int((horizon_item or {}).get("predicted_delay_sec") or peak_delay_sec)

    operational_importance = compute_operational_importance(
        predicted_delay_sec=predicted,
        current_delay_sec=peak_delay_sec,
        horizon_minutes=horizon_minutes,
        geofence_type=str(corridor.get("geofence_type") or "APPROACH_CORRIDOR"),
        impacts_port_access=bool(corridor.get("impacts_port_access", True)),
    )

    method_comparison = build_method_comparison_validation(
        comparisons=comparisons,
        inject_meta=inject_meta,
        hybrid_forecasts=corridor_forecasts,
    )

    slot_recs = recommend_slots_for_corridor(corridor_id, predicted_delay_sec=predicted)

    map_overlay = build_crowd_map_payload(
        corridor_id,
        peak_delay_sec=peak_delay_sec,
        primary_reason=INCIDENT_CAUSE,
        demo_tag="demo_ml_kafka_compare",
    )

    operational_actions = build_operational_actions(
        corridor_id=corridor_id,
        corridor_name=context["corridor_name"],
        port_name=context["port_name"],
        geofence_type=str(corridor.get("geofence_type") or "APPROACH_CORRIDOR"),
        impacts_port_access=bool(corridor.get("impacts_port_access", True)),
        terminals=[str(item) for item in (corridor.get("terminals") or [])],
        predicted_delay_sec=predicted,
        current_delay_sec=peak_delay_sec,
        horizon_minutes=horizon_minutes,
        slot_recommendations=slot_recs.get("recommendations") or [],
        scenario="ml_kafka",
    )

    return {
        "ok": True,
        "corridor_id": corridor_id,
        "corridor_name": context["corridor_name"],
        "port_id": context["port_id"],
        "port_name": context["port_name"],
        "incident_cause": INCIDENT_CAUSE,
        "picked": picked,
        "inject": inject_meta,
        "map_overlay": map_overlay,
        "corridor_forecasts": corridor_forecasts,
        "method_comparison": method_comparison,
        "operational_actions": operational_actions,
        "slot_recommendations": slot_recs,
        "prediction_validation": {
            "passed": method_comparison["passed"],
            "checks": method_comparison["checks"],
            "forecast_count": len(corridor_forecasts),
            "peak_injected_delay_sec": peak_delay_sec,
            "max_predicted_delay_sec": max(
                (int(item.get("predicted_delay_sec") or 0) for item in corridor_forecasts),
                default=peak_delay_sec,
            ),
            "predicted_at_horizon_30_sec": predicted,
            "operational_importance": operational_importance,
            "pulse_eligible": operational_importance in ("action", "critical"),
            "horizons": [
                {
                    "horizon_minutes": row["horizon_minutes"],
                    "predicted_delay_sec": row.get("kafka_trend_sec") or row.get("ml_historical_sec") or 0,
                    "method": "compare",
                    "confidence": "n/a",
                }
                for row in comparisons
            ],
        },
    }
