"""Unified corridor incident demo — crowd pipeline + optional voice dispatch."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from corridor_service import find_corridor_by_id
from demo_baltic_spike_service import ensure_demo_slot_and_spedition, resolve_corridor_context
from demo_crowd_scenario_service import _mark_nearest_slot_at_risk, inject_crowd_scenario
from hybrid_delay_forecaster import DEFAULT_HORIZONS, build_corridor_forecasts
from kafka_prediction_buffer import kafka_prediction_buffer
from operational_action_service import build_operational_actions
from slot_dispatch_service import slot_dispatch_service
from slot_recommendation_service import recommend_slots_for_corridor
from synthetic_crowd_map import build_crowd_map_payload


async def run_corridor_incident_demo(
    *,
    corridor_id: str,
    observation_store: Any,
    enable_voice: bool = False,
    phone_e164: str = "+48000000000",
    owner_user_id: str | None = None,
    peak_delay_sec: int = 960,
    start_delay_sec: int = 120,
    incident_count: int = 6,
    mark_slots_at_risk: bool = True,
    force_call: bool = True,
    voice_call_fn: Any | None = None,
) -> dict[str, Any]:
    context = resolve_corridor_context(corridor_id)
    _port, corridor = find_corridor_by_id(corridor_id)
    incident_cause = f"Incydent demo — {context['corridor_name']}"

    inject_meta = inject_crowd_scenario(
        corridor_id=corridor_id,
        observation_store=observation_store,
        peak_delay_sec=peak_delay_sec,
        start_delay_sec=start_delay_sec,
        incident_count=incident_count,
        incident_cause=incident_cause,
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
    at_risk_slot: dict[str, Any] | None = None
    demo_slot: dict[str, Any] | None = None
    dispatch: dict[str, Any] | None = None

    if enable_voice:
        demo_slot = ensure_demo_slot_and_spedition(
            corridor_id=corridor_id,
            phone_e164=phone_e164,
            owner_user_id=owner_user_id,
        )
        dispatch = await slot_dispatch_service.run_auto_dispatch(
            forecasts=forecasts,
            dry_run=False,
            force=force_call,
            voice_call_fn=voice_call_fn,
            only_slot_ids=[demo_slot["slot_id"]],
        )
        at_risk_slot = {
            "slot_id": demo_slot.get("slot_id"),
            "terminal_code": demo_slot.get("terminal_code"),
            "slot_local": demo_slot.get("slot_local"),
            "status": "at_risk",
        }
    elif mark_slots_at_risk:
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
        primary_reason=incident_cause,
        demo_tag="demo_corridor_incident",
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
        scenario="incident",
    )

    return {
        "ok": True,
        "corridor_id": corridor_id,
        "corridor_name": context["corridor_name"],
        "port_id": context["port_id"],
        "enable_voice": enable_voice,
        "inject": inject_meta,
        "map_overlay": map_overlay,
        "corridor_forecasts": corridor_forecasts,
        "max_predicted_delay_sec": max_predicted,
        "at_risk_slot": at_risk_slot,
        "demo_slot": demo_slot,
        "slot_recommendations": slot_recs,
        "operational_actions": operational_actions,
        "dispatch": dispatch,
    }
