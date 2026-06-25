"""Random high-severity incident to validate forecast / pulse pipeline."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from corridor_service import find_corridor_by_id
from demo_baltic_spike_service import resolve_corridor_context
from demo_crowd_scenario_service import _mark_nearest_slot_at_risk, inject_crowd_scenario
from demo_random_corridor import pick_random_approach_corridor
from hybrid_delay_forecaster import DEFAULT_HORIZONS, build_corridor_forecasts
from kafka_prediction_buffer import kafka_prediction_buffer
from operational_action_service import build_operational_actions, compute_operational_importance
from slot_recommendation_service import recommend_slots_for_corridor
from synthetic_crowd_map import build_crowd_map_payload

LOCAL_TZ = ZoneInfo("Europe/Warsaw")

STRESS_PEAK_DELAY_SEC = int(os.environ.get("DEMO_STRESS_PEAK_DELAY_SEC", "1800"))
STRESS_START_DELAY_SEC = int(os.environ.get("DEMO_STRESS_START_DELAY_SEC", "900"))
STRESS_INCIDENT_COUNT = int(os.environ.get("DEMO_STRESS_INCIDENT_COUNT", "10"))
PULSE_MIN_DELAY_SEC = 480
DISPATCH_MIN_DELAY_SEC = int(os.environ.get("SLOT_DISPATCH_MIN_DELAY_SEC", "600"))

STRESS_INCIDENT_CAUSE = (
    "[TEST STRESS] Ekstremalny zator — weryfikacja silnika predykcji, pulsu mapy i rekomendacji slotów."
)


def build_prediction_validation(
    *,
    corridor_forecasts: list[dict[str, Any]],
    peak_delay_sec: int,
    predicted_at_horizon_sec: int,
    operational_importance: str,
    inject_meta: dict[str, Any],
) -> dict[str, Any]:
    max_predicted = max(
        (int(item.get("predicted_delay_sec") or 0) for item in corridor_forecasts),
        default=0,
    )
    horizons = [
        {
            "horizon_minutes": int(item.get("horizon_minutes") or 0),
            "predicted_delay_sec": int(item.get("predicted_delay_sec") or 0),
            "method": str(item.get("method") or ""),
            "confidence": str(item.get("confidence") or ""),
        }
        for item in sorted(corridor_forecasts, key=lambda row: int(row.get("horizon_minutes") or 0))
    ]
    checks = [
        {
            "id": "samples_injected",
            "label": "Kafka + obserwacje",
            "ok": int(inject_meta.get("samples_injected") or 0) >= 4,
            "detail": f"{inject_meta.get('samples_injected', 0)} próbek, peak {peak_delay_sec}s",
        },
        {
            "id": "forecasts_generated",
            "label": "Prognozy wygenerowane",
            "ok": len(corridor_forecasts) > 0,
            "detail": f"{len(corridor_forecasts)} horyzontów",
        },
        {
            "id": "delay_above_pulse_threshold",
            "label": f"Opóźnienie ≥ {PULSE_MIN_DELAY_SEC // 60} min (próg pulsu)",
            "ok": max_predicted >= PULSE_MIN_DELAY_SEC,
            "detail": f"max prognoza {max_predicted}s ({max_predicted // 60} min)",
        },
        {
            "id": "delay_above_dispatch_threshold",
            "label": f"Opóźnienie ≥ {DISPATCH_MIN_DELAY_SEC // 60} min (próg dispatch)",
            "ok": max_predicted >= DISPATCH_MIN_DELAY_SEC,
            "detail": f"max prognoza {max_predicted}s",
        },
        {
            "id": "importance_action_or_critical",
            "label": "Istotność operacyjna: action / critical",
            "ok": operational_importance in ("action", "critical"),
            "detail": operational_importance,
        },
        {
            "id": "horizon_30_elevated",
            "label": "Horyzont 30 min podniesiony",
            "ok": predicted_at_horizon_sec >= PULSE_MIN_DELAY_SEC,
            "detail": f"30 min → {predicted_at_horizon_sec}s ({predicted_at_horizon_sec // 60} min)",
        },
    ]
    return {
        "passed": all(item["ok"] for item in checks),
        "checks": checks,
        "forecast_count": len(corridor_forecasts),
        "peak_injected_delay_sec": peak_delay_sec,
        "max_predicted_delay_sec": max_predicted,
        "predicted_at_horizon_30_sec": predicted_at_horizon_sec,
        "operational_importance": operational_importance,
        "pulse_eligible": operational_importance in ("action", "critical"),
        "horizons": horizons,
    }


def build_stress_demo_report(
    *,
    corridor_id: str,
    corridor_name: str,
    port_name: str,
    predicted_delay_sec: int,
    horizon_minutes: int,
    operational_actions: dict[str, Any],
    prediction_validation: dict[str, Any],
    at_risk_slot: dict[str, Any] | None,
) -> dict[str, Any]:
    delay_min = max(1, int(round(predicted_delay_sec / 60)))
    now = datetime.now(timezone.utc)
    status = "PASSED" if prediction_validation.get("passed") else "FAILED"
    summary = (
        f"Test stresowy predykcji na {corridor_name} ({port_name} — losowy szlak). "
        f"Wstrzyknięto ekstremalny zator (do {prediction_validation.get('peak_injected_delay_sec', 0) // 60} min). "
        f"Prognoza na {horizon_minutes} min: ok. {delay_min} min. "
        f"Wynik walidacji: {status}."
    )
    sections: list[dict[str, Any]] = [
        {
            "title": "Walidacja predykcji",
            "items": [
                f"{check['label']}: {'OK' if check['ok'] else 'FAIL'} — {check['detail']}"
                for check in (prediction_validation.get("checks") or [])
            ],
        },
        {
            "title": "Kierowca",
            "items": operational_actions.get("driver") or [],
        },
        {
            "title": "Dyspozytor",
            "items": operational_actions.get("dispatcher") or [],
        },
    ]
    if at_risk_slot:
        sections.append(
            {
                "title": "Slot zagrożony",
                "body": (
                    f"{at_risk_slot.get('slot_id')} ({at_risk_slot.get('terminal_code')}) "
                    f"o {at_risk_slot.get('slot_local')}"
                ),
            }
        )
    return {
        "report_id": f"stress-demo-{corridor_id}-{now.strftime('%Y%m%d%H%M%S')}",
        "is_test": True,
        "generated_at": now.isoformat(),
        "headline": STRESS_INCIDENT_CAUSE,
        "corridor_id": corridor_id,
        "corridor_name": corridor_name,
        "port_name": port_name,
        "summary": summary,
        "sections": sections,
        "operational_importance": operational_actions.get("operational_importance"),
        "predicted_delay_sec": predicted_delay_sec,
        "validation_passed": prediction_validation.get("passed"),
    }


def run_prediction_stress_demo(
    *,
    observation_store: Any,
    port_id: str | None = None,
    peak_delay_sec: int = STRESS_PEAK_DELAY_SEC,
    start_delay_sec: int = STRESS_START_DELAY_SEC,
    incident_count: int = STRESS_INCIDENT_COUNT,
    mark_slots_at_risk: bool = True,
) -> dict[str, Any]:
    picked = pick_random_approach_corridor(port_id=port_id)
    corridor_id = picked["corridor_id"]
    context = resolve_corridor_context(corridor_id)
    _port, corridor = find_corridor_by_id(corridor_id)

    inject_meta = inject_crowd_scenario(
        corridor_id=corridor_id,
        observation_store=observation_store,
        peak_delay_sec=peak_delay_sec,
        start_delay_sec=start_delay_sec,
        incident_count=incident_count,
        incident_cause=STRESS_INCIDENT_CAUSE,
    )

    forecasts = build_corridor_forecasts(
        buffer=kafka_prediction_buffer,
        observation_store=observation_store,
        horizons=DEFAULT_HORIZONS,
        corridor_id=corridor_id,
    )
    corridor_forecasts = [item for item in forecasts if item.get("corridor_id") == corridor_id]
    max_predicted = max(
        (int(item.get("predicted_delay_sec") or 0) for item in corridor_forecasts),
        default=peak_delay_sec,
    )
    horizon_item = next(
        (item for item in corridor_forecasts if int(item.get("horizon_minutes") or 0) == 30),
        corridor_forecasts[0] if corridor_forecasts else None,
    )
    horizon_minutes = int((horizon_item or {}).get("horizon_minutes") or 30)
    predicted = int((horizon_item or {}).get("predicted_delay_sec") or max_predicted)

    operational_importance = compute_operational_importance(
        predicted_delay_sec=predicted,
        current_delay_sec=peak_delay_sec,
        horizon_minutes=horizon_minutes,
        geofence_type=str(corridor.get("geofence_type") or "APPROACH_CORRIDOR"),
        impacts_port_access=bool(corridor.get("impacts_port_access", True)),
    )

    prediction_validation = build_prediction_validation(
        corridor_forecasts=corridor_forecasts,
        peak_delay_sec=peak_delay_sec,
        predicted_at_horizon_sec=predicted,
        operational_importance=operational_importance,
        inject_meta=inject_meta,
    )

    now = datetime.now(timezone.utc)
    at_risk_slot = None
    if mark_slots_at_risk:
        at_risk_slot = _mark_nearest_slot_at_risk(corridor_id, now)

    slot_recs = recommend_slots_for_corridor(
        corridor_id,
        predicted_delay_sec=predicted,
    )
    recommendations = slot_recs.get("recommendations") or []

    map_overlay = build_crowd_map_payload(
        corridor_id,
        peak_delay_sec=peak_delay_sec,
        start_delay_sec=start_delay_sec,
        incident_count=incident_count,
        primary_reason=STRESS_INCIDENT_CAUSE,
        demo_tag="demo_prediction_stress",
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
        slot_recommendations=recommendations,
        current_slot=at_risk_slot,
        scenario="stress",
    )

    demo_report = build_stress_demo_report(
        corridor_id=corridor_id,
        corridor_name=context["corridor_name"],
        port_name=context["port_name"],
        predicted_delay_sec=predicted,
        horizon_minutes=horizon_minutes,
        operational_actions=operational_actions,
        prediction_validation=prediction_validation,
        at_risk_slot=at_risk_slot,
    )

    return {
        "ok": True,
        "corridor_id": corridor_id,
        "corridor_name": context["corridor_name"],
        "port_id": context["port_id"],
        "port_name": context["port_name"],
        "incident_cause": STRESS_INCIDENT_CAUSE,
        "picked": picked,
        "inject": inject_meta,
        "map_overlay": map_overlay,
        "corridor_forecasts": corridor_forecasts,
        "max_predicted_delay_sec": max_predicted,
        "at_risk_slot": at_risk_slot,
        "slot_recommendations": slot_recs,
        "operational_actions": operational_actions,
        "prediction_validation": prediction_validation,
        "demo_report": demo_report,
    }
