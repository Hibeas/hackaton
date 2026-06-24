"""
Corridor traffic spike demo — synthetic delay + gate slot + voice dispatch.

Injects a synthetic delay spike on a selected corridor, ensures a gate slot and
spedition for the current half-hour, then runs slot dispatch (Twilio voice).
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from corridor_service import find_corridor_by_id
from hybrid_delay_forecaster import DEFAULT_HORIZONS, build_corridor_forecasts
from kafka_prediction_buffer import kafka_prediction_buffer
from slot_dispatch_service import slot_dispatch_service
from tms.database import tms_database
from tms.store import tms_store
from user_store import user_store

logger = logging.getLogger(__name__)

LOCAL_TZ = ZoneInfo("Europe/Warsaw")
CORRIDOR_ID = "baltic_hub_gate"
CORRIDOR_NAME = "Baltic Hub Gate Area"
PORT_ID = "gdansk"
TERMINAL_CODE = "BCT"
DEFAULT_PHONE = os.environ.get("VOICE_CALL_DEMO_TO", "").strip() or "+48728538889"
SPIKE_DELAY_SEC = 960  # 16 min — above default 600 s threshold

PORT_TERMINAL_FALLBACK: dict[str, str] = {
    "gdansk": "DCT",
    "gdynia": "GCT",
    "szczecin": "DBPS",
    "swinoujscie": "PLSZZ",
}


def _now_local() -> datetime:
    return datetime.now(LOCAL_TZ)


def _slot_window_for_now(now_local: datetime | None = None) -> tuple[int, int, str]:
    """Current 30-minute gate slot aligned to local clock."""
    local = now_local or _now_local()
    minute_bucket = (local.minute // 30) * 30
    start = local.replace(minute=minute_bucket, second=0, microsecond=0)
    return start.hour, start.minute, start


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip()).strip("-").upper()
    return cleaned[:24] or "CORRIDOR"


def resolve_corridor_context(corridor_id: str) -> dict[str, Any]:
    port, corridor = find_corridor_by_id(corridor_id)
    terminal_map = tms_store.corridor_terminal_map()
    mapped = terminal_map.get(corridor_id) or []
    corridor_terminals = [str(item) for item in (corridor.get("terminals") or [])]
    port_terminals = [str(item) for item in (port.get("terminals") or [])]
    terminal_code = (
        (mapped[0] if mapped else None)
        or (corridor_terminals[0] if corridor_terminals else None)
        or (port_terminals[0] if port_terminals else None)
        or PORT_TERMINAL_FALLBACK.get(str(port["id"]), "DCT")
    )

    return {
        "corridor_id": corridor_id,
        "corridor_name": str(corridor.get("name") or corridor_id),
        "port_id": str(port["id"]),
        "port_name": str(port.get("name") or port["id"]),
        "terminal_code": terminal_code,
        "corridor_ids_for_slot": [corridor_id],
    }


def ensure_demo_slot_and_spedition(
    *,
    corridor_id: str,
    phone_e164: str = DEFAULT_PHONE,
    owner_user_id: str | None = None,
    contact_name: str | None = None,
    company_name: str | None = None,
) -> dict[str, Any]:
    """Upsert TMS slot for current half-hour + spedition with target phone."""
    context = resolve_corridor_context(corridor_id)
    now_local = _now_local()
    start_hour, start_minute, start = _slot_window_for_now(now_local)
    terminal_code = context["terminal_code"]
    corridor_slug = _slug(corridor_id)
    slot_id = f"SLOT-{terminal_code}-DEMO-{corridor_slug}-{start.strftime('%H%M')}"
    window_end = start + timedelta(minutes=45)
    window_start_utc = start.astimezone(timezone.utc)
    window_end_utc = window_end.astimezone(timezone.utc)
    booking_ref = f"MSC-DEMO-{context['corridor_id']}-{now_local.strftime('%Y%m%d-%H%M')}"

    operator = _find_user_by_phone(phone_e164)
    display_name = company_name or (
        operator.get("full_name") if operator else f"Demo {context['corridor_name']}"
    )
    contact = contact_name or (operator.get("full_name") if operator else "Dyspozytor")

    tms_database.upsert_carrier(
        provider_id="mock_msc",
        display_name="Mock MSC Gate TMS",
        adapter="mock_msc_v1",
        active=True,
        description_pl=f"Demo armator MSC — slot na bieżącą godzinę ({context['corridor_name']}).",
    )
    tms_database.upsert_slot_template(
        "mock_msc",
        {
            "slot_id": slot_id,
            "terminal_code": terminal_code,
            "port_id": context["port_id"],
            "start_hour": start_hour,
            "start_minute": start_minute,
            "duration_minutes": 45,
            "container_count": 2,
            "booking_ref": booking_ref,
            "status": "confirmed",
            "corridor_ids": context["corridor_ids_for_slot"],
            "window_start_at": window_start_utc.isoformat(),
            "window_end_at": window_end_utc.isoformat(),
            "owner_user_id": owner_user_id,
        },
    )
    spedition_id = f"SPD-DEMO-{_slug(corridor_id)}"
    tms_database.clear_spedition_links_for_slot("mock_msc", slot_id)
    tms_database.upsert_spedition(
        "mock_msc",
        {
            "spedition_id": spedition_id,
            "company_name": display_name or "Demo Ops",
            "contact_name": contact or "Dyspozytor",
            "phone_e164": phone_e164,
            "email": operator.get("email") if operator else "demo@port-ai.local",
        },
        [slot_id],
    )

    return {
        "corridor_id": corridor_id,
        "corridor_name": context["corridor_name"],
        "port_id": context["port_id"],
        "terminal_code": terminal_code,
        "slot_id": slot_id,
        "slot_local": f"{start_hour:02d}:{start_minute:02d}",
        "spedition_id": spedition_id,
        "phone_e164": phone_e164,
        "operator_user_id": owner_user_id or (operator.get("id") if operator else None),
        "user_database": user_store.backend_name,
    }


def _find_user_by_phone(phone_e164: str) -> dict[str, Any] | None:
    normalized = phone_e164.strip()
    if user_store.backend == "postgres":
        with user_store._pg_conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, email, full_name, phone_e164, created_at
                FROM users WHERE phone_e164 = %s
                LIMIT 1
                """,
                (normalized,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "id": str(row[0]),
                "email": row[1],
                "full_name": row[2],
                "phone_e164": row[3],
                "created_at": row[4].isoformat() if row[4] else None,
            }

    with user_store._sqlite_connect() as connection:
        row = connection.execute(
            """
            SELECT id, email, full_name, phone_e164, created_at
            FROM users WHERE phone_e164 = ?
            LIMIT 1
            """,
            (normalized,),
        ).fetchone()
        if row is None:
            return None
        return dict(row)


def inject_corridor_spike(
    *,
    corridor_id: str,
    observation_store: Any,
    peak_delay_sec: int = SPIKE_DELAY_SEC,
) -> dict[str, Any]:
    """Inject escalating delay samples into Kafka buffer + observation store."""
    context = resolve_corridor_context(corridor_id)
    now = datetime.now(timezone.utc)
    samples = 8
    snapshots: list[dict[str, Any]] = []

    for index in range(samples):
        observed_at = now - timedelta(minutes=28 - index * 4)
        delay = 90.0 + (peak_delay_sec - 90.0) * (index / max(1, samples - 1))
        snapshot = {
            "corridor_id": corridor_id,
            "port_id": context["port_id"],
            "timestamp": observed_at.isoformat(),
            "metrics": {
                "total_delay_sec": delay,
                "max_delay_sec": delay,
                "incident_count": 4 + index,
                "demo_spike": True,
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


def build_forecasts_after_spike(
    *,
    corridor_id: str,
    observation_store: Any,
    peak_delay_sec: int = SPIKE_DELAY_SEC,
) -> list[dict[str, Any]]:
    context = resolve_corridor_context(corridor_id)
    forecasts = build_corridor_forecasts(
        buffer=kafka_prediction_buffer,
        observation_store=observation_store,
        horizons=DEFAULT_HORIZONS,
        corridor_id=corridor_id,
    )
    forecasts.append(
        {
            "corridor_id": corridor_id,
            "corridor_name": context["corridor_name"],
            "port_id": context["port_id"],
            "horizon_minutes": 60,
            "predicted_delay_sec": peak_delay_sec,
            "method": "demo_spike",
            "confidence": "high",
        }
    )
    return forecasts


async def run_corridor_spike_demo(
    *,
    corridor_id: str,
    observation_store: Any,
    phone_e164: str = DEFAULT_PHONE,
    owner_user_id: str | None = None,
    peak_delay_sec: int = SPIKE_DELAY_SEC,
    dry_run: bool = False,
    force_call: bool = True,
    voice_call_fn: Any | None = None,
) -> dict[str, Any]:
    slot_info = ensure_demo_slot_and_spedition(
        corridor_id=corridor_id,
        phone_e164=phone_e164,
        owner_user_id=owner_user_id,
    )
    spike_info = inject_corridor_spike(
        corridor_id=corridor_id,
        observation_store=observation_store,
        peak_delay_sec=peak_delay_sec,
    )
    forecasts = build_forecasts_after_spike(
        corridor_id=corridor_id,
        observation_store=observation_store,
        peak_delay_sec=peak_delay_sec,
    )
    corridor_forecasts = [item for item in forecasts if item.get("corridor_id") == corridor_id]
    max_predicted = max(
        (int(item.get("predicted_delay_sec") or 0) for item in corridor_forecasts),
        default=0,
    )

    dispatch = await slot_dispatch_service.run_auto_dispatch(
        forecasts=forecasts,
        dry_run=dry_run,
        force=force_call,
        voice_call_fn=voice_call_fn,
        only_slot_ids=[slot_info["slot_id"]],
    )

    return {
        "ok": True,
        "corridor_id": corridor_id,
        "phone_e164": phone_e164,
        "dry_run": dry_run,
        "slot": slot_info,
        "spike": spike_info,
        "corridor_forecasts": corridor_forecasts,
        "max_predicted_delay_sec": max_predicted,
        "dispatch": {
            "alert_count": dispatch.get("alert_count"),
            "calls": dispatch.get("calls"),
            "alerts": [
                {
                    "corridor_name": alert.get("corridor_name"),
                    "slot_id": alert.get("slot", {}).get("slot_id"),
                    "voice_message": alert.get("voice_message"),
                    "phones": [
                        sp.get("phone_e164") for sp in (alert.get("speditions") or [])
                    ],
                }
                for alert in (dispatch.get("alerts") or [])
            ],
        },
        "note": f"Users DB: {user_store.backend_name} | TMS/observations on same DATABASE_URL.",
    }


async def run_baltic_hub_spike_demo(
    *,
    observation_store: Any,
    phone_e164: str = DEFAULT_PHONE,
    peak_delay_sec: int = SPIKE_DELAY_SEC,
    dry_run: bool = False,
    force_call: bool = True,
    voice_call_fn: Any | None = None,
) -> dict[str, Any]:
    return await run_corridor_spike_demo(
        corridor_id=CORRIDOR_ID,
        observation_store=observation_store,
        phone_e164=phone_e164,
        peak_delay_sec=peak_delay_sec,
        dry_run=dry_run,
        force_call=force_call,
        voice_call_fn=voice_call_fn,
    )
