"""
Slot dispatch orchestration — forecast risk → gate slots → speditions → voice calls.

When hybrid forecast predicts strong delay on a corridor, find today's gate slots
at affected terminals and notify responsible speditions (Twilio voice).
Only slots marked at_risk receive calls; max one active/answered call per booking_ref.
"""

from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from tms.canonical import CanonicalSlot, CanonicalSpedition
from tms.database import tms_database
from tms.store import TmsStore, tms_store

logger = logging.getLogger(__name__)

LOCAL_TZ = ZoneInfo("Europe/Warsaw")

SLOT_DISPATCH_MIN_DELAY_SEC = int(os.environ.get("SLOT_DISPATCH_MIN_DELAY_SEC", "600"))
SLOT_DISPATCH_MIN_HORIZON_MIN = int(os.environ.get("SLOT_DISPATCH_MIN_HORIZON_MIN", "30"))
SLOT_DISPATCH_AUTO_ENABLED = os.environ.get("SLOT_DISPATCH_AUTO_ENABLED", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
SLOT_DISPATCH_CALL_COOLDOWN_MIN = int(os.environ.get("SLOT_DISPATCH_CALL_COOLDOWN_MIN", "45"))
SLOT_DISPATCH_LOOKAHEAD_MIN = int(os.environ.get("SLOT_DISPATCH_LOOKAHEAD_MIN", "180"))


class SlotDispatchService:
    def __init__(self, store: TmsStore | None = None) -> None:
        self.store = store or tms_store
        self._call_cooldowns: dict[str, datetime] = {}
        self._history: list[dict[str, Any]] = []

    def build_dispatch_plan(
        self,
        *,
        forecasts: list[dict[str, Any]],
        reference: datetime | None = None,
    ) -> dict[str, Any]:
        now = reference or datetime.now(timezone.utc)
        day = now.astimezone(LOCAL_TZ).date()
        self.store.refresh()

        corridor_map = self.store.corridor_terminal_map()
        terminal_labels = self.store.terminal_labels()
        all_slots = self.store.slots_for_day(day)

        high_risk = self._high_risk_forecasts(forecasts)
        alerts: list[dict[str, Any]] = []

        for forecast in high_risk:
            corridor_id = str(forecast.get("corridor_id") or "")
            terminals = set(corridor_map.get(corridor_id, []))
            corridor_slots = [
                slot
                for slot in all_slots
                if slot["terminal_code"] in terminals or corridor_id in slot.get("corridor_ids", [])
            ]
            matching_slots = [
                slot for slot in corridor_slots if self._slot_in_risk_window(slot, now, forecast)
            ]
            if not matching_slots:
                continue

            slot_ids = [slot["slot_id"] for slot in matching_slots]
            speditions = self.store.speditions_for_slots(slot_ids)
            spedition_by_slot = self._index_speditions(speditions)

            for slot in matching_slots:
                provider_id = str(slot.get("provider_id") or "mock_msc")
                tms_database.mark_slot_at_risk(provider_id, slot["slot_id"], at_risk_since=now)
                slot = {**slot, "status": "at_risk"}

                assigned = spedition_by_slot.get(slot["slot_id"], [])
                primary = assigned[:1]
                message = self._build_alert_message(
                    slot=slot,
                    forecast=forecast,
                    terminal_labels=terminal_labels,
                    speditions=primary,
                )
                alerts.append(
                    {
                        "alert_id": self._alert_fingerprint(corridor_id, slot["slot_id"], forecast),
                        "corridor_id": corridor_id,
                        "corridor_name": forecast.get("corridor_name"),
                        "port_id": forecast.get("port_id"),
                        "predicted_delay_sec": int(forecast.get("predicted_delay_sec") or 0),
                        "horizon_minutes": int(forecast.get("horizon_minutes") or 0),
                        "forecast_method": forecast.get("method"),
                        "slot": slot,
                        "speditions": primary,
                        "voice_message": message,
                        "slot_local_time": self._format_slot_local(slot),
                    }
                )

        alerts = self._dedupe_alerts_by_slot(alerts)
        alerts.sort(key=lambda item: item["predicted_delay_sec"], reverse=True)
        return {
            "generated_at": now.isoformat(),
            "day": day.isoformat(),
            "threshold_delay_sec": SLOT_DISPATCH_MIN_DELAY_SEC,
            "min_horizon_minutes": SLOT_DISPATCH_MIN_HORIZON_MIN,
            "high_risk_forecast_count": len(high_risk),
            "alert_count": len(alerts),
            "alerts": alerts,
            "providers": self.store.list_providers(),
        }

    async def run_auto_dispatch(
        self,
        *,
        forecasts: list[dict[str, Any]],
        reference: datetime | None = None,
        voice_call_fn: Any | None = None,
        dry_run: bool = False,
        force: bool = False,
    ) -> dict[str, Any]:
        plan = self.build_dispatch_plan(forecasts=forecasts, reference=reference)
        if dry_run:
            plan["auto_enabled"] = SLOT_DISPATCH_AUTO_ENABLED
            plan["dry_run"] = True
            plan["calls"] = []
            return plan

        if voice_call_fn is None:
            from voice_call_service import make_automated_voice_call

            voice_call_fn = make_automated_voice_call

        now = reference or datetime.now(timezone.utc)
        calls: list[dict[str, Any]] = []
        phones_called_this_run: set[str] = set()

        for alert in plan.get("alerts") or []:
            slot = alert.get("slot") or {}
            if slot.get("status") != "at_risk":
                calls.append(
                    {
                        "status": "skipped_not_at_risk",
                        "slot_id": slot.get("slot_id"),
                    }
                )
                continue

            booking_ref = str(slot.get("booking_ref") or "")
            provider_id = str(slot.get("provider_id") or "mock_msc")

            if booking_ref and tms_database.booking_has_answered_call(booking_ref):
                calls.append(
                    {
                        "status": "skipped_booking_answered",
                        "booking_ref": booking_ref,
                        "slot_id": slot.get("slot_id"),
                    }
                )
                continue

            if booking_ref and tms_database.booking_has_active_call(booking_ref):
                calls.append(
                    {
                        "status": "skipped_booking_active",
                        "booking_ref": booking_ref,
                        "slot_id": slot.get("slot_id"),
                    }
                )
                continue

            speditions = alert.get("speditions") or []
            if not speditions:
                calls.append(
                    {
                        "status": "skipped_no_spedition",
                        "slot_id": slot.get("slot_id"),
                    }
                )
                continue

            spedition = speditions[0]
            phone = str(spedition.get("phone_e164") or "").strip()
            if not phone:
                continue

            if phone in phones_called_this_run:
                calls.append(
                    {
                        "status": "skipped_phone_duplicate",
                        "phone": phone,
                        "slot_id": slot.get("slot_id"),
                    }
                )
                continue

            fingerprint = self._call_fingerprint(alert["alert_id"], spedition["spedition_id"])
            if not force and self._in_cooldown(fingerprint, now):
                calls.append(
                    {
                        "status": "skipped_cooldown",
                        "fingerprint": fingerprint,
                        "spedition_id": spedition["spedition_id"],
                        "phone": phone,
                    }
                )
                continue

            message = str(alert.get("voice_message") or "")
            try:
                result = await voice_call_fn(phone, message)
                self._call_cooldowns[fingerprint] = now
                phones_called_this_run.add(phone)

                if booking_ref:
                    tms_database.record_slot_call(
                        provider_id=provider_id,
                        booking_ref=booking_ref,
                        slot_id=str(slot.get("slot_id") or ""),
                        spedition_id=str(spedition.get("spedition_id") or ""),
                        phone_e164=phone,
                        call_sid=result.get("call_sid"),
                        call_status="initiated",
                    )

                entry = {
                    "status": "called",
                    "fingerprint": fingerprint,
                    "spedition_id": spedition["spedition_id"],
                    "company_name": spedition.get("company_name"),
                    "phone": phone,
                    "slot_id": slot.get("slot_id"),
                    "booking_ref": booking_ref,
                    "call_sid": result.get("call_sid"),
                    "strategy": result.get("strategy"),
                }
                calls.append(entry)
                self._history.append({**entry, "at": now.isoformat(), "message": message})
                logger.info(
                    "Slot dispatch call %s -> %s (%s, booking=%s)",
                    spedition["spedition_id"],
                    phone,
                    slot.get("slot_id"),
                    booking_ref,
                )
            except Exception as exc:
                logger.warning(
                    "Slot dispatch call failed for %s: %s",
                    spedition.get("spedition_id"),
                    exc,
                )
                if booking_ref:
                    try:
                        tms_database.record_slot_call(
                            provider_id=provider_id,
                            booking_ref=booking_ref,
                            slot_id=str(slot.get("slot_id") or ""),
                            spedition_id=str(spedition.get("spedition_id") or ""),
                            phone_e164=phone,
                            call_sid=None,
                            call_status="failed",
                        )
                    except Exception as record_exc:
                        logger.warning("Failed to record failed call for %s: %s", booking_ref, record_exc)

                calls.append(
                    {
                        "status": "error",
                        "fingerprint": fingerprint,
                        "spedition_id": spedition["spedition_id"],
                        "phone": phone,
                        "error": str(exc),
                    }
                )

        plan["auto_enabled"] = True
        plan["calls"] = calls
        return plan

    def recent_history(self, limit: int = 20) -> list[dict[str, Any]]:
        return list(reversed(self._history[-limit:]))

    def _dedupe_alerts_by_slot(self, alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        best_by_slot: dict[str, dict[str, Any]] = {}
        for alert in alerts:
            slot_id = str(alert.get("slot", {}).get("slot_id") or "")
            if not slot_id:
                continue
            existing = best_by_slot.get(slot_id)
            if existing is None or int(alert.get("predicted_delay_sec") or 0) > int(
                existing.get("predicted_delay_sec") or 0
            ):
                best_by_slot[slot_id] = alert
        return list(best_by_slot.values())

    def _high_risk_forecasts(self, forecasts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        results = [
            item
            for item in forecasts
            if int(item.get("predicted_delay_sec") or 0) >= SLOT_DISPATCH_MIN_DELAY_SEC
            and int(item.get("horizon_minutes") or 0) >= SLOT_DISPATCH_MIN_HORIZON_MIN
        ]
        results.sort(
            key=lambda item: (
                int(item.get("predicted_delay_sec") or 0),
                int(item.get("horizon_minutes") or 0),
            ),
            reverse=True,
        )
        return results

    def _slot_in_risk_window(
        self,
        slot: CanonicalSlot,
        now: datetime,
        forecast: dict[str, Any],
    ) -> bool:
        start = datetime.fromisoformat(slot["window_start"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(slot["window_end"].replace("Z", "+00:00"))
        horizon = int(forecast.get("horizon_minutes") or SLOT_DISPATCH_MIN_HORIZON_MIN)
        risk_until = now + timedelta(minutes=max(horizon, SLOT_DISPATCH_LOOKAHEAD_MIN))
        return start <= risk_until and end >= now

    def _index_speditions(
        self,
        speditions: list[CanonicalSpedition],
    ) -> dict[str, list[CanonicalSpedition]]:
        mapping: dict[str, list[CanonicalSpedition]] = {}
        for spedition in speditions:
            for slot_id in spedition.get("slot_ids") or []:
                mapping.setdefault(slot_id, []).append(spedition)
        return mapping

    def _build_alert_message(
        self,
        *,
        slot: CanonicalSlot,
        forecast: dict[str, Any],
        terminal_labels: dict[str, str],
        speditions: list[CanonicalSpedition],
    ) -> str:
        delay_min = max(1, int(round(int(forecast.get("predicted_delay_sec") or 0) / 60)))
        terminal = terminal_labels.get(slot["terminal_code"], slot["terminal_code"])
        slot_time = self._format_slot_local(slot)
        company = speditions[0]["company_name"] if speditions else "spedycja"
        booking = slot.get("booking_ref") or slot["slot_id"]
        corridor = forecast.get("corridor_name") or forecast.get("corridor_id") or "korytarz portowy"
        return (
            f"Uwaga, {company}. Port A I wykrył wysokie ryzyko opóźnienia na dojeździe do {terminal}. "
            f"Prognoza około {delay_min} minut na odcinku {corridor}. "
            f"Dotyczy slotu bramowego o {slot_time}, rezerwacja {booking}. "
            f"Rozważ opóźnienie wyjazdu lub trasę alternatywną."
        )

    def _format_slot_local(self, slot: CanonicalSlot) -> str:
        start = datetime.fromisoformat(slot["window_start"].replace("Z", "+00:00")).astimezone(LOCAL_TZ)
        end = datetime.fromisoformat(slot["window_end"].replace("Z", "+00:00")).astimezone(LOCAL_TZ)
        return f"{start.strftime('%H:%M')}–{end.strftime('%H:%M')}"

    def _alert_fingerprint(self, corridor_id: str, slot_id: str, forecast: dict[str, Any]) -> str:
        raw = f"{corridor_id}|{slot_id}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    def _call_fingerprint(self, alert_id: str, spedition_id: str) -> str:
        return hashlib.sha1(f"{alert_id}|{spedition_id}".encode("utf-8")).hexdigest()[:20]

    def _in_cooldown(self, fingerprint: str, now: datetime) -> bool:
        last = self._call_cooldowns.get(fingerprint)
        if last is None:
            return False
        return now - last < timedelta(minutes=SLOT_DISPATCH_CALL_COOLDOWN_MIN)


slot_dispatch_service = SlotDispatchService()
