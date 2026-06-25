"""Operational action hints for drivers and dispatchers (aligned with frontend operationalImportance)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("Europe/Warsaw")

IMPORTANCE_LABELS = {
    "monitor": "monitor",
    "caution": "obserwacja",
    "action": "działanie",
    "critical": "krytyczny",
}

DISPATCH_HINTS = {
    "monitor": "kontynuuj monitoring",
    "caution": "obserwuj co 10–15 min",
    "action": "rozważ zmianę okna bramowego lub trasy",
    "critical": "wstrzymaj dispatch lub przesuń slot natychmiast",
}


def _delay_score(effective_delay_sec: int) -> int:
    if effective_delay_sec < 300:
        return 0
    if effective_delay_sec < 480:
        return 1
    if effective_delay_sec < 720:
        return 2
    return 3


def _urgency_score(horizon_minutes: int) -> int:
    if horizon_minutes <= 15:
        return 2
    if horizon_minutes <= 30:
        return 1
    if horizon_minutes <= 60:
        return 0
    return -1


def _access_score(geofence_type: str | None, impacts_port_access: bool) -> int:
    if not impacts_port_access:
        return 0
    if geofence_type in ("GATE_ZONE", "PORT_ACCESS"):
        return 3
    if geofence_type in ("APPROACH_CORRIDOR", "BOTTLENECK", "CRITICAL_INFRASTRUCTURE"):
        return 2
    if geofence_type == "BUFFER_ZONE":
        return 0
    return 1


def compute_operational_importance(
    *,
    predicted_delay_sec: int,
    current_delay_sec: int,
    horizon_minutes: int,
    geofence_type: str | None = None,
    impacts_port_access: bool = True,
) -> str:
    effective = max(int(predicted_delay_sec or 0), int(current_delay_sec or 0))
    trend = -1 if int(predicted_delay_sec or 0) < int(current_delay_sec or 0) - 60 else 0
    score = (
        _delay_score(effective)
        + _urgency_score(int(horizon_minutes or 30))
        + _access_score(geofence_type, impacts_port_access)
        + trend
    )
    if score <= 3:
        return "monitor"
    if score <= 5:
        return "caution"
    if score <= 6:
        return "action"
    return "critical"


def _horizon_until_label(horizon_minutes: int, reference: datetime | None = None) -> str:
    now = reference or datetime.now(timezone.utc)
    target = now + timedelta(minutes=max(1, horizon_minutes))
    return target.astimezone(LOCAL_TZ).strftime("%H:%M")


def build_operational_actions(
    *,
    corridor_id: str,
    corridor_name: str,
    port_name: str,
    geofence_type: str | None,
    impacts_port_access: bool,
    terminals: list[str],
    predicted_delay_sec: int,
    current_delay_sec: int,
    horizon_minutes: int,
    slot_recommendations: list[dict[str, Any]] | None = None,
    current_slot: dict[str, Any] | None = None,
    scenario: str = "forecast",
) -> dict[str, Any]:
    importance = compute_operational_importance(
        predicted_delay_sec=predicted_delay_sec,
        current_delay_sec=current_delay_sec,
        horizon_minutes=horizon_minutes,
        geofence_type=geofence_type,
        impacts_port_access=impacts_port_access,
    )
    delay_min = max(1, int(round(max(predicted_delay_sec, current_delay_sec) / 60)))
    until_time = _horizon_until_label(horizon_minutes)
    terminal_label = ", ".join(terminals) if terminals else "terminal"

    driver: list[str] = []
    if importance in ("action", "critical"):
        driver.append(
            f"Opóźnij wyjazd o ~{delay_min} min — prognoza na {corridor_name} ({port_name})."
        )
    else:
        driver.append(f"Monitoruj {corridor_name} — opóźnienie ~{delay_min} min.")

    driver.append(f"Unikaj odcinka {corridor_name} do ok. {until_time} — rosnący korek.")
    if geofence_type in ("GATE_ZONE", "PORT_ACCESS"):
        driver.append(f"Priorytet: bezpośredni dojazd do {terminal_label} — strefa bramy.")
    elif impacts_port_access:
        driver.append(f"Dojazd do {terminal_label} — korytarz podejściowy pod presją.")

    recommendations = slot_recommendations or []
    alt = None
    current_slot_id = str((current_slot or {}).get("slot_id") or "")
    for item in recommendations:
        if str(item.get("slot_id") or "") != current_slot_id:
            alt = item
            break

    dispatcher: list[str] = []
    if current_slot:
        dispatcher.append(
            f"Slot {current_slot.get('slot_id')} ({current_slot.get('terminal_code', '')}) "
            f"— okno {current_slot.get('slot_local', '')}."
        )
    dispatcher.append(
        f"Status: {IMPORTANCE_LABELS.get(importance, importance)} — "
        f"{DISPATCH_HINTS.get(importance, 'monitoruj')}."
    )
    if alt:
        dispatcher.append(
            f"Rozważ przesunięcie na {alt.get('terminal_label')} o {alt.get('window_local')} "
            f"(+{alt.get('slack_minutes')} min zapasu)."
        )
    else:
        dispatcher.append("Brak lepszego okna bramowego dziś — monitoruj prognozę co 10–15 min.")

    voice_parts = [
        f"Uwaga. Port A I wykrył ryzyko na {corridor_name}.",
        f"Prognoza około {delay_min} minut za {horizon_minutes} minut.",
    ]
    if current_slot:
        voice_parts.append(
            f"Dotyczy slotu {current_slot.get('slot_id')} o {current_slot.get('slot_local', '')}."
        )
    if alt:
        voice_parts.append(
            f"Propozycja: przesuń na {alt.get('terminal_label')} o {alt.get('window_local')}."
        )
    else:
        voice_parts.append("Rozważ opóźnienie wyjazdu lub trasę alternatywną.")

    return {
        "scenario": scenario,
        "operational_importance": importance,
        "driver": driver,
        "dispatcher": dispatcher,
        "voice_summary": " ".join(voice_parts),
        "slot_recommendations": recommendations[:3],
    }
