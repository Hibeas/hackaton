"""User gate-slot bookings (awizacje) resolved from TMS by account owner."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from tms.database import tms_database
from tms.store import tms_store

LOCAL_TZ = ZoneInfo("Europe/Warsaw")
PLACEHOLDER_PROVIDER = "mock_msc"
PLACEHOLDER_REF_PREFIX = "MSC-PH-"


def build_my_bookings(
    user_id: str,
    *,
    reference: datetime | None = None,
    include_past_hours: int = 6,
    phone_e164: str = "",
    contact_name: str = "",
    company_name: str = "",
    seed_placeholders: bool = True,
) -> dict[str, Any]:
    if seed_placeholders:
        ensure_placeholder_bookings(
            user_id,
            phone_e164=phone_e164,
            contact_name=contact_name,
            company_name=company_name,
            reference=reference,
        )
    now = reference or datetime.now(timezone.utc)
    day = now.astimezone(LOCAL_TZ).date()
    cutoff = now - timedelta(hours=include_past_hours)
    terminal_labels = tms_store.terminal_labels()

    templates = tms_database.fetch_bookings_for_user(user_id.strip())
    booking_refs: list[str] = []
    items: list[dict[str, Any]] = []

    for template in templates:
        raw_status = str(template.get("status") or "confirmed")
        if raw_status == "cancelled":
            continue

        slot = tms_database.materialize_slot(
            str(template.get("provider_id") or "mock_msc"),
            template,
            day,
        )
        window_start = datetime.fromisoformat(slot["window_start"].replace("Z", "+00:00"))
        window_end = datetime.fromisoformat(slot["window_end"].replace("Z", "+00:00"))
        if window_end < cutoff:
            continue

        booking_ref = str(slot.get("booking_ref") or "")
        if booking_ref:
            booking_refs.append(booking_ref)

        effective_status = _effective_booking_status(
            raw_status,
            window_start=window_start,
            window_end=window_end,
            now=now,
        )

        items.append(
            {
                "slot_id": slot["slot_id"],
                "booking_ref": booking_ref,
                "provider_id": slot["provider_id"],
                "terminal_code": slot["terminal_code"],
                "terminal_label": terminal_labels.get(slot["terminal_code"], slot["terminal_code"]),
                "port_id": slot["port_id"],
                "window_start": slot["window_start"],
                "window_end": slot["window_end"],
                "window_local": _format_window_local(window_start, window_end),
                "status": effective_status,
                "at_risk_since": template.get("at_risk_since"),
                "container_count": slot["container_count"],
                "corridor_ids": slot.get("corridor_ids") or [],
                "spedition_id": template.get("spedition_id"),
                "company_name": template.get("company_name"),
                "contact_name": template.get("contact_name"),
                "phone_e164": template.get("phone_e164"),
                "call": None,
            }
        )

    items = _dedupe_bookings(items)
    calls_by_booking = tms_database.fetch_latest_calls_for_bookings(booking_refs)
    for item in items:
        ref = item.get("booking_ref") or ""
        if ref and ref in calls_by_booking:
            item["call"] = calls_by_booking[ref]

    items.sort(key=lambda row: row.get("window_start") or "")

    at_risk_count = sum(1 for item in items if item.get("status") == "at_risk")

    return {
        "user_id": user_id.strip(),
        "generated_at": now.isoformat(),
        "day": day.isoformat(),
        "total": len(items),
        "at_risk_count": at_risk_count,
        "bookings": items,
    }


def _effective_booking_status(
    raw_status: str,
    *,
    window_start: datetime,
    window_end: datetime,
    now: datetime,
) -> str:
    if window_end < now:
        return "completed"
    if raw_status == "at_risk":
        return "at_risk"
    return raw_status or "confirmed"


def _dedupe_bookings(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_slot: dict[str, dict[str, Any]] = {}
    for item in items:
        slot_id = str(item.get("slot_id") or "")
        if not slot_id:
            continue
        existing = by_slot.get(slot_id)
        if existing is None or str(item.get("window_start") or "") >= str(existing.get("window_start") or ""):
            by_slot[slot_id] = item
    return list(by_slot.values())


def _format_window_local(start: datetime, end: datetime) -> str:
    start_local = start.astimezone(LOCAL_TZ)
    end_local = end.astimezone(LOCAL_TZ)
    if start_local.date() == end_local.date():
        return f"{start_local.strftime('%d.%m %H:%M')}–{end_local.strftime('%H:%M')}"
    return f"{start_local.strftime('%d.%m %H:%M')}–{end_local.strftime('%d.%m %H:%M')}"


def ensure_placeholder_bookings(
    user_id: str,
    *,
    phone_e164: str = "",
    contact_name: str = "",
    company_name: str = "",
    reference: datetime | None = None,
) -> int:
    normalized_user = user_id.strip()
    if not normalized_user or tms_database.user_has_placeholder_bookings(normalized_user):
        return 0

    now = reference or datetime.now(timezone.utc)
    local_now = now.astimezone(LOCAL_TZ)
    slot_prefix = f"SLOT-PH-{normalized_user.replace('-', '')[:8]}"
    phone = phone_e164.strip() or "+48000000000"
    contact = contact_name.strip() or "Dyspozytor"
    company = company_name.strip() or "Port-AI Demo Spedycja"

    tms_database.upsert_carrier(
        provider_id=PLACEHOLDER_PROVIDER,
        display_name="Mock MSC Gate TMS",
        adapter="mock_msc_v1",
        active=True,
        description_pl="Demo awizacje użytkownika.",
    )

    specs = [
        {
            "suffix": "GCT-1",
            "terminal_code": "GCT",
            "port_id": "gdynia",
            "offset_hours": 2,
            "duration_minutes": 45,
            "container_count": 2,
            "status": "confirmed",
            "corridor_ids": ["ul_polska", "s6_wezel_estakada"],
        },
        {
            "suffix": "DCT-1",
            "terminal_code": "DCT",
            "port_id": "gdynia",
            "offset_hours": 5,
            "duration_minutes": 30,
            "container_count": 1,
            "status": "confirmed",
            "corridor_ids": ["trasa_sucharskiego", "tunel_martwa_wisla"],
        },
        {
            "suffix": "BCT-1",
            "terminal_code": "BCT",
            "port_id": "gdynia",
            "offset_hours": 26,
            "duration_minutes": 30,
            "container_count": 2,
            "status": "confirmed",
            "corridor_ids": ["baltic_hub_gate", "marynarki_polskiej"],
        },
        {
            "suffix": "GCT-RISK",
            "terminal_code": "GCT",
            "port_id": "gdynia",
            "offset_hours": 1,
            "duration_minutes": 30,
            "container_count": 3,
            "status": "at_risk",
            "corridor_ids": ["estakada_kwiatkowskiego", "janka_wisniewskiego"],
        },
    ]

    created = 0
    for index, spec in enumerate(specs, start=1):
        start_local = (local_now + timedelta(hours=int(spec["offset_hours"]))).replace(
            minute=0,
            second=0,
            microsecond=0,
        )
        if start_local <= local_now:
            start_local += timedelta(hours=1)
        duration = int(spec["duration_minutes"])
        end_local = start_local + timedelta(minutes=duration)
        start_utc = start_local.astimezone(timezone.utc)
        end_utc = end_local.astimezone(timezone.utc)
        slot_id = f"{slot_prefix}-{spec['suffix']}"
        booking_ref = f"{PLACEHOLDER_REF_PREFIX}{local_now.strftime('%Y%m%d')}-{index:02d}"

        template: dict[str, Any] = {
            "slot_id": slot_id,
            "terminal_code": spec["terminal_code"],
            "port_id": spec["port_id"],
            "start_hour": start_local.hour,
            "start_minute": start_local.minute,
            "duration_minutes": duration,
            "container_count": int(spec["container_count"]),
            "booking_ref": booking_ref,
            "status": spec["status"],
            "corridor_ids": list(spec["corridor_ids"]),
            "window_start_at": start_utc.isoformat(),
            "window_end_at": end_utc.isoformat(),
            "owner_user_id": normalized_user,
        }
        if spec["status"] == "at_risk":
            template["at_risk_since"] = now.isoformat()

        tms_database.upsert_slot_template(PLACEHOLDER_PROVIDER, template)
        spedition_id = f"SPD-PH-{normalized_user.replace('-', '')[:8]}-{spec['suffix']}"
        tms_database.clear_spedition_links_for_slot(PLACEHOLDER_PROVIDER, slot_id)
        tms_database.upsert_spedition(
            PLACEHOLDER_PROVIDER,
            {
                "spedition_id": spedition_id,
                "company_name": company,
                "contact_name": contact,
                "phone_e164": phone,
                "email": "demo@port-ai.local",
            },
            [slot_id],
        )
        created += 1

    return created


def cancel_my_booking(
    user_id: str,
    *,
    provider_id: str,
    slot_id: str,
) -> dict[str, Any]:
    updated = tms_database.update_slot_status_for_owner(
        provider_id.strip(),
        slot_id.strip(),
        user_id.strip(),
        "cancelled",
    )
    if not updated:
        raise ValueError("booking_not_found")
    return {"ok": True, "slot_id": slot_id, "status": "cancelled"}


def reschedule_my_booking(
    user_id: str,
    *,
    provider_id: str,
    slot_id: str,
    offset_minutes: int | None = None,
    window_start_at: datetime | None = None,
) -> dict[str, Any]:
    if window_start_at is not None:
        updated = tms_database.set_slot_window_for_owner(
            provider_id.strip(),
            slot_id.strip(),
            user_id.strip(),
            window_start_at=window_start_at,
        )
    elif offset_minutes is not None and offset_minutes > 0:
        updated = tms_database.shift_slot_window_for_owner(
            provider_id.strip(),
            slot_id.strip(),
            user_id.strip(),
            offset_minutes=offset_minutes,
        )
    else:
        raise ValueError("invalid_reschedule_payload")
    if updated is None:
        raise ValueError("booking_not_found")
    window_start = tms_database._parse_optional_timestamp(updated.get("window_start_at"))
    window_end = tms_database._parse_optional_timestamp(updated.get("window_end_at"))
    if window_start is None or window_end is None:
        raise ValueError("booking_reschedule_failed")
    return {
        "ok": True,
        "slot_id": slot_id,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "window_local": _format_window_local(window_start, window_end),
        "status": updated.get("status") or "confirmed",
    }
