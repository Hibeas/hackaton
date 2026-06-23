"""
One-shot Baltic Hub traffic spike demo — slot + forecast + voice call.

Injects synthetic delay spike on baltic_hub_gate, ensures a gate slot and spedition
for the current hour (phone +48728538889), then runs slot dispatch.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from hybrid_delay_forecaster import DEFAULT_HORIZONS, build_corridor_forecasts
from kafka_prediction_buffer import kafka_prediction_buffer
from slot_dispatch_service import slot_dispatch_service
from tms.database import tms_database
from user_store import user_store

logger = logging.getLogger(__name__)

LOCAL_TZ = ZoneInfo("Europe/Warsaw")
CORRIDOR_ID = "baltic_hub_gate"
CORRIDOR_NAME = "Baltic Hub Gate Area"
PORT_ID = "gdansk"
TERMINAL_CODE = "BCT"
DEFAULT_PHONE = "+48728538889"
SPIKE_DELAY_SEC = 960  # 16 min — above default 600 s threshold


def _now_local() -> datetime:
    return datetime.now(LOCAL_TZ)


def _slot_window_for_now(now_local: datetime | None = None) -> tuple[int, int, str]:
    """Current 30-minute gate slot aligned to local clock."""
    local = now_local or _now_local()
    minute_bucket = (local.minute // 30) * 30
    start = local.replace(minute=minute_bucket, second=0, microsecond=0)
    slot_id = f"SLOT-BCT-DEMO-{start.strftime('%H%M')}"
    return start.hour, start.minute, slot_id


def ensure_demo_slot_and_spedition(
    *,
    phone_e164: str = DEFAULT_PHONE,
    contact_name: str | None = None,
    company_name: str | None = None,
) -> dict[str, Any]:
    """Upsert TMS slot for current hour + spedition with target phone."""
    now_local = _now_local()
    start_hour, start_minute, slot_id = _slot_window_for_now(now_local)

    operator = _find_user_by_phone(phone_e164)
    display_name = company_name or (
        operator.get("full_name") if operator else "Operator Baltic Hub"
    )
    contact = contact_name or (operator.get("full_name") if operator else "Dyspozytor")

    tms_database.upsert_carrier(
        provider_id="mock_msc",
        display_name="Mock MSC Gate TMS",
        adapter="mock_msc_v1",
        active=True,
        description_pl="Demo armator MSC — slot na bieżącą godzinę (Baltic Hub).",
    )
    tms_database.upsert_slot_template(
        "mock_msc",
        {
            "slot_id": slot_id,
            "terminal_code": TERMINAL_CODE,
            "port_id": PORT_ID,
            "start_hour": start_hour,
            "start_minute": start_minute,
            "duration_minutes": 45,
            "container_count": 2,
            "booking_ref": f"MSC-DEMO-BCT-{now_local.strftime('%Y%m%d-%H%M')}",
            "status": "confirmed",
            "corridor_ids": [CORRIDOR_ID, "marynarki_polskiej"],
        },
    )
    spedition_id = "SPD-DEMO-BALTIC-OPS"
    tms_database.upsert_spedition(
        "mock_msc",
        {
            "spedition_id": spedition_id,
            "company_name": display_name or "Baltic Hub Ops",
            "contact_name": contact or "Dyspozytor",
            "phone_e164": phone_e164,
            "email": operator.get("email") if operator else "demo@baltic-hub.local",
        },
        [slot_id],
    )

    return {
        "slot_id": slot_id,
        "slot_local": f"{start_hour:02d}:{start_minute:02d}",
        "spedition_id": spedition_id,
        "phone_e164": phone_e164,
        "operator_user_id": operator.get("id") if operator else None,
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


def inject_baltic_hub_spike(
    *,
    observation_store: Any,
    peak_delay_sec: int = SPIKE_DELAY_SEC,
) -> dict[str, Any]:
    """Inject escalating delay samples into Kafka buffer + observation store."""
    now = datetime.now(timezone.utc)
    samples = 8
    snapshots: list[dict[str, Any]] = []

    for index in range(samples):
        observed_at = now - timedelta(minutes=28 - index * 4)
        delay = 90.0 + (peak_delay_sec - 90.0) * (index / max(1, samples - 1))
        snapshot = {
            "corridor_id": CORRIDOR_ID,
            "port_id": PORT_ID,
            "timestamp": observed_at.isoformat(),
            "metrics": {
                "total_delay_sec": delay,
                "max_delay_sec": delay,
                "incident_count": 4 + index,
                "demo_spike": True,
            },
            "corridor_name": CORRIDOR_NAME,
        }
        snapshots.append(snapshot)
        kafka_prediction_buffer.ingest_snapshot(snapshot)

    observation_store.append_batch(snapshots)

    return {
        "corridor_id": CORRIDOR_ID,
        "peak_delay_sec": peak_delay_sec,
        "samples_injected": samples,
        "observation_database": observation_store.backend_name,
    }


def build_forecasts_after_spike(
    *,
    observation_store: Any,
    peak_delay_sec: int = SPIKE_DELAY_SEC,
) -> list[dict[str, Any]]:
    forecasts = build_corridor_forecasts(
        buffer=kafka_prediction_buffer,
        observation_store=observation_store,
        horizons=DEFAULT_HORIZONS,
        corridor_id=CORRIDOR_ID,
    )
    # Dispatch threshold requires horizon >= 30 min; short kafka trend alone may not qualify.
    forecasts.append(
        {
            "corridor_id": CORRIDOR_ID,
            "corridor_name": CORRIDOR_NAME,
            "port_id": PORT_ID,
            "horizon_minutes": 60,
            "predicted_delay_sec": peak_delay_sec,
            "method": "demo_spike",
            "confidence": "high",
        }
    )
    return forecasts


async def run_baltic_hub_spike_demo(
    *,
    observation_store: Any,
    phone_e164: str = DEFAULT_PHONE,
    peak_delay_sec: int = SPIKE_DELAY_SEC,
    dry_run: bool = False,
    force_call: bool = True,
    voice_call_fn: Any | None = None,
) -> dict[str, Any]:
    slot_info = ensure_demo_slot_and_spedition(phone_e164=phone_e164)
    spike_info = inject_baltic_hub_spike(
        observation_store=observation_store,
        peak_delay_sec=peak_delay_sec,
    )
    forecasts = build_forecasts_after_spike(
        observation_store=observation_store,
        peak_delay_sec=peak_delay_sec,
    )
    baltic_forecasts = [item for item in forecasts if item.get("corridor_id") == CORRIDOR_ID]
    max_predicted = max(
        (int(item.get("predicted_delay_sec") or 0) for item in baltic_forecasts),
        default=0,
    )

    dispatch = await slot_dispatch_service.run_auto_dispatch(
        forecasts=forecasts,
        dry_run=dry_run,
        force=force_call,
        voice_call_fn=voice_call_fn,
    )

    return {
        "ok": True,
        "slot": slot_info,
        "spike": spike_info,
        "baltic_forecasts": baltic_forecasts,
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
