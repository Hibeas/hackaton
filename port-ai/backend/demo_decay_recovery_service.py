"""Inject spike then declining samples — validate importance drop and pulse ineligibility."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
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

PULSE_MIN_DELAY_SEC = 480
IMPORTANCE_RANK = {"monitor": 0, "caution": 1, "action": 2, "critical": 3}

INCIDENT_CAUSE = (
    "[TEST DECAY] Spike -> zanik opoznien — weryfikacja spadku istotnosci i braku pulsu."
)


def inject_decay_samples(
    *,
    corridor_id: str,
    observation_store: Any,
    delays_sec: tuple[int, ...] = (120, 120, 120, 120, 120, 120, 120, 120),
    minutes_apart: int = 4,
    incident_cause: str | None = None,
) -> dict[str, Any]:
    context = resolve_corridor_context(corridor_id)
    now = datetime.now(timezone.utc)
    cause = incident_cause or f"Zanik korka (demo) — {context['corridor_name']}"
    snapshots: list[dict[str, Any]] = []

    for index, delay in enumerate(delays_sec):
        observed_at = now - timedelta(minutes=(len(delays_sec) - 1 - index) * minutes_apart)
        snapshot = {
            "corridor_id": corridor_id,
            "port_id": context["port_id"],
            "timestamp": observed_at.isoformat(),
            "metrics": {
                "total_delay_sec": float(delay),
                "max_delay_sec": float(delay),
                "incident_count": 1,
                "primary_incident_category": 6,
                "top_incident_causes": [cause],
                "demo_decay": True,
            },
            "corridor_name": context["corridor_name"],
        }
        snapshots.append(snapshot)
        kafka_prediction_buffer.ingest_snapshot(snapshot)

    observation_store.append_batch(snapshots)

    return {
        "corridor_id": corridor_id,
        "samples_injected": len(snapshots),
        "delays_sec": list(delays_sec),
        "final_delay_sec": delays_sec[-1] if delays_sec else 0,
    }


def _phase_metrics(
    *,
    corridor: dict[str, Any],
    corridor_forecasts: list[dict[str, Any]],
    current_delay_sec: int,
    at_spike_peak: bool = False,
) -> dict[str, Any]:
    horizon_item = next(
        (item for item in corridor_forecasts if int(item.get("horizon_minutes") or 0) == 30),
        corridor_forecasts[0] if corridor_forecasts else None,
    )
    horizon_minutes = int((horizon_item or {}).get("horizon_minutes") or 30)
    predicted = int((horizon_item or {}).get("predicted_delay_sec") or current_delay_sec)
    max_predicted = max(
        (int(item.get("predicted_delay_sec") or 0) for item in corridor_forecasts),
        default=predicted,
    )
    if at_spike_peak:
        predicted = max(predicted, current_delay_sec)
        max_predicted = max(max_predicted, current_delay_sec)

    importance = compute_operational_importance(
        predicted_delay_sec=predicted,
        current_delay_sec=current_delay_sec,
        horizon_minutes=horizon_minutes,
        geofence_type=str(corridor.get("geofence_type") or "APPROACH_CORRIDOR"),
        impacts_port_access=bool(corridor.get("impacts_port_access", True)),
    )
    pulse_eligible = (
        importance in ("action", "critical")
        and max(predicted, current_delay_sec) >= PULSE_MIN_DELAY_SEC
    )
    return {
        "horizon_minutes": horizon_minutes,
        "predicted_at_horizon_30_sec": predicted,
        "max_predicted_delay_sec": max_predicted,
        "current_delay_sec": current_delay_sec,
        "operational_importance": importance,
        "pulse_eligible": pulse_eligible,
        "forecasts": corridor_forecasts,
    }


def build_decay_validation(
    *,
    phase_spike: dict[str, Any],
    phase_recovery: dict[str, Any],
    spike_inject: dict[str, Any],
    decay_inject: dict[str, Any],
) -> dict[str, Any]:
    spike_rank = IMPORTANCE_RANK.get(str(phase_spike.get("operational_importance")), 0)
    recovery_rank = IMPORTANCE_RANK.get(str(phase_recovery.get("operational_importance")), 0)

    checks = [
        {
            "id": "spike_injected",
            "label": "Faza spike wstrzyknięta",
            "ok": int(spike_inject.get("samples_injected") or 0) >= 4,
            "detail": f"{spike_inject.get('samples_injected', 0)} probek, peak {spike_inject.get('peak_delay_sec', 0)}s",
        },
        {
            "id": "phase1_elevated",
            "label": "Istotnosc po spike: action / critical",
            "ok": phase_spike.get("operational_importance") in ("action", "critical"),
            "detail": str(phase_spike.get("operational_importance")),
        },
        {
            "id": "phase1_pulse",
            "label": f"Puls mapy po spike (>={PULSE_MIN_DELAY_SEC // 60} min)",
            "ok": bool(phase_spike.get("pulse_eligible")),
            "detail": f"max {phase_spike.get('max_predicted_delay_sec', 0)}s",
        },
        {
            "id": "decay_injected",
            "label": "Faza zaniku wstrzyknięta",
            "ok": int(decay_inject.get("samples_injected") or 0) >= 3,
            "detail": f"koncowka {decay_inject.get('final_delay_sec', 0)}s",
        },
        {
            "id": "phase2_importance_dropped",
            "label": "Istotnosc spadla po zaniku",
            "ok": recovery_rank < spike_rank,
            "detail": f"{phase_spike.get('operational_importance')} -> {phase_recovery.get('operational_importance')}",
        },
        {
            "id": "phase2_pulse_off",
            "label": "Puls wylaczony po zaniku",
            "ok": not bool(phase_recovery.get("pulse_eligible")),
            "detail": f"max {phase_recovery.get('max_predicted_delay_sec', 0)}s, {phase_recovery.get('operational_importance')}",
        },
        {
            "id": "phase2_below_threshold",
            "label": f"Prognoza < {PULSE_MIN_DELAY_SEC // 60} min po zaniku",
            "ok": int(phase_recovery.get("max_predicted_delay_sec") or 0) < PULSE_MIN_DELAY_SEC,
            "detail": f"30 min -> {phase_recovery.get('predicted_at_horizon_30_sec', 0)}s",
        },
    ]

    return {
        "passed": all(item["ok"] for item in checks),
        "checks": checks,
        "phase_spike": phase_spike,
        "phase_recovery": phase_recovery,
        "pulse_min_delay_sec": PULSE_MIN_DELAY_SEC,
    }


def run_decay_recovery_demo(
    *,
    observation_store: Any,
    port_id: str | None = None,
    corridor_id: str | None = None,
    peak_delay_sec: int = 960,
    decay_delays_sec: tuple[int, ...] = (120, 120, 120, 120, 120, 120, 120, 120),
) -> dict[str, Any]:
    if corridor_id:
        picked = {"corridor_id": corridor_id.strip(), "port_id": port_id}
        context = resolve_corridor_context(corridor_id.strip())
    else:
        picked = pick_random_approach_corridor(port_id=port_id)
        corridor_id = picked["corridor_id"]
        context = resolve_corridor_context(corridor_id)

    _port, corridor = find_corridor_by_id(corridor_id)

    spike_inject = inject_crowd_scenario(
        corridor_id=corridor_id,
        observation_store=observation_store,
        peak_delay_sec=peak_delay_sec,
        incident_cause=INCIDENT_CAUSE,
    )

    spike_forecasts = build_corridor_forecasts(
        buffer=kafka_prediction_buffer,
        observation_store=observation_store,
        horizons=DEFAULT_HORIZONS,
        corridor_id=corridor_id,
    )
    corridor_spike = [item for item in spike_forecasts if item.get("corridor_id") == corridor_id]
    phase_spike = _phase_metrics(
        corridor=corridor,
        corridor_forecasts=corridor_spike,
        current_delay_sec=peak_delay_sec,
        at_spike_peak=True,
    )

    kafka_prediction_buffer.clear_corridor(corridor_id)
    decay_inject = inject_decay_samples(
        corridor_id=corridor_id,
        observation_store=observation_store,
        delays_sec=decay_delays_sec,
        incident_cause=f"Zanik po spike — {context['corridor_name']}",
    )

    recovery_forecasts = build_corridor_forecasts(
        buffer=kafka_prediction_buffer,
        observation_store=observation_store,
        horizons=DEFAULT_HORIZONS,
        corridor_id=corridor_id,
    )
    corridor_recovery = [item for item in recovery_forecasts if item.get("corridor_id") == corridor_id]
    final_delay = int(decay_delays_sec[-1]) if decay_delays_sec else 120
    phase_recovery = _phase_metrics(
        corridor=corridor,
        corridor_forecasts=corridor_recovery,
        current_delay_sec=final_delay,
        at_spike_peak=False,
    )

    decay_validation = build_decay_validation(
        phase_spike=phase_spike,
        phase_recovery=phase_recovery,
        spike_inject=spike_inject,
        decay_inject=decay_inject,
    )

    predicted = int(phase_recovery.get("predicted_at_horizon_30_sec") or final_delay)
    horizon_minutes = int(phase_recovery.get("horizon_minutes") or 30)
    slot_recs = recommend_slots_for_corridor(corridor_id, predicted_delay_sec=predicted)

    map_overlay = build_crowd_map_payload(
        corridor_id,
        peak_delay_sec=peak_delay_sec,
        primary_reason=INCIDENT_CAUSE,
        demo_tag="demo_decay_recovery",
    )

    operational_actions = build_operational_actions(
        corridor_id=corridor_id,
        corridor_name=context["corridor_name"],
        port_name=context["port_name"],
        geofence_type=str(corridor.get("geofence_type") or "APPROACH_CORRIDOR"),
        impacts_port_access=bool(corridor.get("impacts_port_access", True)),
        terminals=[str(item) for item in (corridor.get("terminals") or [])],
        predicted_delay_sec=predicted,
        current_delay_sec=final_delay,
        horizon_minutes=horizon_minutes,
        slot_recommendations=slot_recs.get("recommendations") or [],
        scenario="decay",
    )

    demo_report = {
        "report_id": f"decay-demo-{corridor_id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
        "is_test": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "headline": INCIDENT_CAUSE,
        "corridor_id": corridor_id,
        "corridor_name": context["corridor_name"],
        "port_name": context["port_name"],
        "summary": (
            f"Spike -> {phase_spike.get('operational_importance')} (puls: "
            f"{'tak' if phase_spike.get('pulse_eligible') else 'nie'}), "
            f"zanik -> {phase_recovery.get('operational_importance')} (puls: "
            f"{'tak' if phase_recovery.get('pulse_eligible') else 'nie'})."
        ),
        "sections": [
            {
                "title": "Faza spike",
                "items": [
                    f"Istotnosc: {phase_spike.get('operational_importance')}",
                    f"Prognoza 30 min: {phase_spike.get('predicted_at_horizon_30_sec')}s",
                    f"Puls: {'TAK' if phase_spike.get('pulse_eligible') else 'NIE'}",
                ],
            },
            {
                "title": "Faza zaniku",
                "items": [
                    f"Istotnosc: {phase_recovery.get('operational_importance')}",
                    f"Prognoza 30 min: {phase_recovery.get('predicted_at_horizon_30_sec')}s",
                    f"Puls: {'TAK' if phase_recovery.get('pulse_eligible') else 'NIE'}",
                ],
            },
        ],
        "validation_passed": decay_validation.get("passed"),
    }

    return {
        "ok": True,
        "corridor_id": corridor_id,
        "corridor_name": context["corridor_name"],
        "port_id": context["port_id"],
        "port_name": context["port_name"],
        "incident_cause": INCIDENT_CAUSE,
        "picked": picked,
        "inject": {"spike": spike_inject, "decay": decay_inject},
        "map_overlay": map_overlay,
        "decay_validation": decay_validation,
        "corridor_forecasts": corridor_recovery,
        "operational_actions": operational_actions,
        "slot_recommendations": slot_recs,
        "demo_report": demo_report,
        "prediction_validation": {
            "passed": decay_validation["passed"],
            "checks": decay_validation["checks"],
            "forecast_count": len(corridor_recovery),
            "peak_injected_delay_sec": peak_delay_sec,
            "max_predicted_delay_sec": int(phase_recovery.get("max_predicted_delay_sec") or 0),
            "predicted_at_horizon_30_sec": predicted,
            "operational_importance": phase_recovery.get("operational_importance"),
            "pulse_eligible": phase_recovery.get("pulse_eligible"),
            "horizons": [
                {
                    "horizon_minutes": int(item.get("horizon_minutes") or 0),
                    "predicted_delay_sec": int(item.get("predicted_delay_sec") or 0),
                    "method": str(item.get("method") or ""),
                    "confidence": str(item.get("confidence") or ""),
                }
                for item in corridor_recovery
            ],
        },
    }
