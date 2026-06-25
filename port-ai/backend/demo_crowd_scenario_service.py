"""Inject synthetic crowd into live pipeline (Kafka, observations, forecasts, slots)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from corridor_service import find_corridor_by_id
from demo_baltic_spike_service import resolve_corridor_context
from hybrid_delay_forecaster import DEFAULT_HORIZONS, build_corridor_forecasts
from kafka_prediction_buffer import kafka_prediction_buffer
from operational_action_service import build_operational_actions
from slot_recommendation_service import recommend_slots_for_corridor
from synthetic_crowd_map import build_crowd_map_payload
from tms.database import tms_database
from tms.store import tms_store

LOCAL_TZ = ZoneInfo("Europe/Warsaw")


def inject_crowd_scenario(
    *,
    corridor_id: str,
    observation_store: Any,
    peak_delay_sec: int = 960,
    start_delay_sec: int = 120,
    incident_count: int = 6,
    incident_cause: str | None = None,
) -> dict[str, Any]:
    context = resolve_corridor_context(corridor_id)
    now = datetime.now(timezone.utc)
    samples = 8
    snapshots: list[dict[str, Any]] = []
    cause = incident_cause or f"Sztuczny tłum (demo) — {context['corridor_name']}"

    for index in range(samples):
        observed_at = now - timedelta(minutes=28 - index * 4)
        ratio = index / max(1, samples - 1)
        delay = float(start_delay_sec + (peak_delay_sec - start_delay_sec) * ratio)
        snapshot = {
            "corridor_id": corridor_id,
            "port_id": context["port_id"],
            "timestamp": observed_at.isoformat(),
            "metrics": {
                "total_delay_sec": delay,
                "max_delay_sec": delay,
                "incident_count": incident_count,
                "primary_incident_category": 6,
                "top_incident_causes": [cause],
                "demo_crowd": True,
            },
            "corridor_name": context["corridor_name"],
        }
        snapshots.append(snapshot)
        kafka_prediction_buffer.ingest_snapshot(snapshot)

    observation_store.append_batch(snapshots)

    return {
        "corridor_id": corridor_id,
        "corridor_name": context["corridor_name"],
        "port_id": context["port_id"],
        "peak_delay_sec": peak_delay_sec,
        "samples_injected": samples,
        "observation_database": observation_store.backend_name,
    }


def _mark_nearest_slot_at_risk(corridor_id: str, reference: datetime) -> dict[str, Any] | None:
    tms_store.refresh()
    day = reference.astimezone(timezone.utc).date()
    corridor_map = tms_store.corridor_terminal_map()
    terminals = set(corridor_map.get(corridor_id, []))
    candidates = [
        slot
        for slot in tms_store.slots_for_day(day)
        if corridor_id in (slot.get("corridor_ids") or [])
        or str(slot.get("terminal_code") or "") in terminals
    ]
    if not candidates:
        return None

    def sort_key(slot: dict[str, Any]) -> tuple[int, str]:
        try:
            start = datetime.fromisoformat(str(slot.get("window_start") or "").replace("Z", "+00:00"))
        except ValueError:
            return (999_999, str(slot.get("slot_id") or ""))
        delta = abs(int((start - reference).total_seconds()))
        return (delta, str(slot.get("slot_id") or ""))

    slot = sorted(candidates, key=sort_key)[0]
    provider_id = str(slot.get("provider_id") or "mock_msc")
    tms_database.mark_slot_at_risk(provider_id, str(slot["slot_id"]), at_risk_since=reference)
    local_start = datetime.fromisoformat(str(slot["window_start"]).replace("Z", "+00:00"))
    local = local_start.astimezone(LOCAL_TZ)
    return {
        "slot_id": slot.get("slot_id"),
        "terminal_code": slot.get("terminal_code"),
        "slot_local": local.strftime("%H:%M"),
        "status": "at_risk",
    }


def run_crowd_scenario_demo(
    *,
    corridor_id: str,
    observation_store: Any,
    peak_delay_sec: int = 960,
    start_delay_sec: int = 120,
    incident_count: int = 6,
    mark_slots_at_risk: bool = True,
) -> dict[str, Any]:
    context = resolve_corridor_context(corridor_id)
    _port, corridor = find_corridor_by_id(corridor_id)

    inject_meta = inject_crowd_scenario(
        corridor_id=corridor_id,
        observation_store=observation_store,
        peak_delay_sec=peak_delay_sec,
        start_delay_sec=start_delay_sec,
        incident_count=incident_count,
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

    now = datetime.now(timezone.utc)
    at_risk_slot = None
    if mark_slots_at_risk:
        at_risk_slot = _mark_nearest_slot_at_risk(corridor_id, now)

    slot_recs = recommend_slots_for_corridor(
        corridor_id,
        predicted_delay_sec=predicted,
    )

    map_overlay = build_crowd_map_payload(
        corridor_id,
        peak_delay_sec=peak_delay_sec,
        start_delay_sec=start_delay_sec,
        incident_count=incident_count,
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
        current_slot=at_risk_slot,
        scenario="crowd",
    )

    return {
        "ok": True,
        "corridor_id": corridor_id,
        "corridor_name": context["corridor_name"],
        "inject": inject_meta,
        "map_overlay": map_overlay,
        "corridor_forecasts": corridor_forecasts,
        "max_predicted_delay_sec": max_predicted,
        "at_risk_slot": at_risk_slot,
        "slot_recommendations": slot_recs,
        "operational_actions": operational_actions,
    }
