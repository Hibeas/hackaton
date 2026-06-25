"""Recommend alternative gate slots when corridor delay threatens a booking window."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from tms.store import tms_store

LOCAL_TZ = ZoneInfo("Europe/Warsaw")
MIN_BUFFER_SEC = 900


def _parse_iso(value: str) -> datetime:
    raw = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def recommend_slots_for_corridor(
    corridor_id: str,
    *,
    predicted_delay_sec: int = 0,
    limit: int = 3,
    reference: datetime | None = None,
) -> dict[str, Any]:
    now = reference or datetime.now(timezone.utc)
    day = now.astimezone(LOCAL_TZ).date()
    buffer_sec = max(int(predicted_delay_sec or 0), MIN_BUFFER_SEC)
    earliest_arrival = now + timedelta(seconds=buffer_sec)

    tms_store.refresh()
    corridor_map = tms_store.corridor_terminal_map()
    terminal_labels = tms_store.terminal_labels()
    terminals = set(corridor_map.get(corridor_id, []))

    candidates: list[dict[str, Any]] = []
    for slot in tms_store.slots_for_day(day):
        status = str(slot.get("status") or "confirmed")
        if status == "cancelled":
            continue

        slot_corridors = {str(item) for item in (slot.get("corridor_ids") or [])}
        terminal_code = str(slot.get("terminal_code") or "")
        if corridor_id not in slot_corridors and terminal_code not in terminals:
            continue

        try:
            window_start = _parse_iso(str(slot.get("window_start") or ""))
            window_end = _parse_iso(str(slot.get("window_end") or ""))
        except ValueError:
            continue

        if window_start < earliest_arrival:
            continue

        minutes_until = max(0, int((window_start - now).total_seconds() // 60))
        slack_min = max(0, int((window_start - earliest_arrival).total_seconds() // 60))
        at_risk = status == "at_risk"

        score = slack_min
        if at_risk:
            score -= 120
        if status == "confirmed":
            score += 30

        reason_key = "at_risk" if at_risk else ("comfortable" if slack_min >= 45 else "tight")
        terminal_label = terminal_labels.get(terminal_code, terminal_code)
        local_start = window_start.astimezone(LOCAL_TZ)

        candidates.append(
            {
                "slot_id": slot.get("slot_id"),
                "provider_id": slot.get("provider_id"),
                "terminal_code": terminal_code,
                "terminal_label": terminal_label,
                "port_id": slot.get("port_id"),
                "booking_ref": slot.get("booking_ref"),
                "status": status,
                "window_start": window_start.isoformat(),
                "window_end": window_end.isoformat(),
                "window_local": local_start.strftime("%H:%M"),
                "window_date_local": local_start.strftime("%Y-%m-%d"),
                "minutes_until": minutes_until,
                "slack_minutes": slack_min,
                "score": score,
                "reason_key": reason_key,
            }
        )

    candidates.sort(key=lambda item: (-int(item["score"]), item["window_start"]))
    recommendations = candidates[: max(1, min(limit, 5))]

    return {
        "corridor_id": corridor_id,
        "generated_at": now.isoformat(),
        "predicted_delay_sec": int(predicted_delay_sec or 0),
        "buffer_sec": buffer_sec,
        "earliest_arrival_at": earliest_arrival.isoformat(),
        "recommendation_count": len(recommendations),
        "recommendations": recommendations,
    }
