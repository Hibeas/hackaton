"""Tests for TMS mock store and slot dispatch orchestration."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch, patch
from zoneinfo import ZoneInfo

from slot_dispatch_service import SlotDispatchService, SLOT_DISPATCH_MIN_DELAY_SEC
from tms.database import TmsDatabase
from tms.providers.mock_msc import MockMscTmsProvider
from tms.store import TmsStore

LOCAL_TZ = ZoneInfo("Europe/Warsaw")


class MockMscProviderTests(unittest.TestCase):
    def test_fetch_slots_materializes_today(self) -> None:
        provider = MockMscTmsProvider()
        day = date(2026, 6, 23)
        slots = provider.fetch_slots(day=day)
        self.assertGreaterEqual(len(slots), 6)
        first = slots[0]
        start = datetime.fromisoformat(first["window_start"].replace("Z", "+00:00")).astimezone(LOCAL_TZ)
        self.assertEqual(start.date(), day)

    def test_speditions_linked_to_slots(self) -> None:
        provider = MockMscTmsProvider()
        speditions = provider.fetch_speditions(slot_ids=["SLOT-DCT-0800"])
        self.assertEqual(len(speditions), 1)
        self.assertEqual(speditions[0]["spedition_id"], "SPD-TRANS-BALTIC")


class SlotDispatchServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = TmsStore(providers=[MockMscTmsProvider()])
        self.service = SlotDispatchService(store=self.store)

    def test_high_risk_forecast_matches_dct_slot(self) -> None:
        day = date(2026, 6, 23)
        reference = datetime(2026, 6, 23, 6, 0, tzinfo=LOCAL_TZ).astimezone(timezone.utc)
        forecasts = [
            {
                "corridor_id": "trasa_sucharskiego",
                "corridor_name": "Trasa Sucharskiego",
                "port_id": "gdynia",
                "horizon_minutes": 60,
                "predicted_delay_sec": SLOT_DISPATCH_MIN_DELAY_SEC + 120,
                "method": "ml_historical",
            }
        ]
        plan = self.service.build_dispatch_plan(forecasts=forecasts, reference=reference)
        self.assertGreater(plan["alert_count"], 0)
        slot_ids = {alert["slot"]["slot_id"] for alert in plan["alerts"]}
        self.assertIn("SLOT-DCT-0800", slot_ids)
        alert = plan["alerts"][0]
        self.assertTrue(alert["speditions"])
        self.assertIn("Trans-Baltic", alert["voice_message"])
        self.assertEqual(alert["slot"]["status"], "at_risk")

    def test_low_risk_forecast_produces_no_alerts(self) -> None:
        reference = datetime.now(timezone.utc)
        forecasts = [
            {
                "corridor_id": "trasa_sucharskiego",
                "port_id": "gdynia",
                "horizon_minutes": 60,
                "predicted_delay_sec": 120,
                "method": "ml_historical",
            }
        ]
        plan = self.service.build_dispatch_plan(forecasts=forecasts, reference=reference)
        self.assertEqual(plan["alert_count"], 0)

    def test_dedupe_alerts_for_same_slot(self) -> None:
        reference = datetime(2026, 6, 23, 6, 0, tzinfo=LOCAL_TZ).astimezone(timezone.utc)
        forecasts = [
            {
                "corridor_id": "trasa_sucharskiego",
                "corridor_name": "Trasa Sucharskiego",
                "port_id": "gdynia",
                "horizon_minutes": 60,
                "predicted_delay_sec": 900,
                "method": "ml_historical",
            },
            {
                "corridor_id": "trasa_sucharskiego",
                "corridor_name": "Trasa Sucharskiego",
                "port_id": "gdynia",
                "horizon_minutes": 120,
                "predicted_delay_sec": 700,
                "method": "ml_historical",
            },
        ]
        plan = self.service.build_dispatch_plan(forecasts=forecasts, reference=reference)
        dct_alerts = [a for a in plan["alerts"] if a["slot"]["slot_id"] == "SLOT-DCT-0800"]
        self.assertEqual(len(dct_alerts), 1)
        self.assertEqual(dct_alerts[0]["predicted_delay_sec"], 900)

    def test_dry_run_does_not_call(self) -> None:
        async def _run() -> None:
            forecasts = [
                {
                    "corridor_id": "trasa_sucharskiego",
                    "corridor_name": "Trasa Sucharskiego",
                    "port_id": "gdynia",
                    "horizon_minutes": 60,
                    "predicted_delay_sec": 900,
                    "method": "ml_historical",
                }
            ]
            mock_call = AsyncMock(return_value={"call_sid": "CA-test", "strategy": "twilio_say"})
            result = await self.service.run_auto_dispatch(
                forecasts=forecasts,
                reference=datetime(2026, 6, 23, 6, 0, tzinfo=LOCAL_TZ).astimezone(timezone.utc),
                voice_call_fn=mock_call,
                dry_run=True,
            )
            self.assertTrue(result["dry_run"])
            self.assertEqual(result["calls"], [])
            mock_call.assert_not_called()

        import asyncio

        asyncio.run(_run())

    def test_one_call_per_booking_and_phone(self) -> None:
        async def _run() -> None:
            with tempfile.TemporaryDirectory() as tmp:
                db = TmsDatabase(db_path=Path(tmp) / "tms_test.db")
                provider = MockMscTmsProvider(database=db)
                service = SlotDispatchService(store=TmsStore(providers=[provider]))
                forecasts = [
                    {
                        "corridor_id": "trasa_sucharskiego",
                        "corridor_name": "Trasa Sucharskiego",
                        "port_id": "gdynia",
                        "horizon_minutes": 60,
                        "predicted_delay_sec": 900,
                        "method": "ml_historical",
                    },
                    {
                        "corridor_id": "trasa_sucharskiego",
                        "corridor_name": "Trasa Sucharskiego",
                        "port_id": "gdynia",
                        "horizon_minutes": 120,
                        "predicted_delay_sec": 850,
                        "method": "ml_historical",
                    },
                ]
                mock_call = AsyncMock(return_value={"call_sid": "CA-test", "strategy": "twilio_say"})
                reference = datetime(2026, 6, 23, 6, 0, tzinfo=LOCAL_TZ).astimezone(timezone.utc)
                with patch("slot_dispatch_service.tms_database", db):
                    result = await service.run_auto_dispatch(
                        forecasts=forecasts,
                        reference=reference,
                        voice_call_fn=mock_call,
                        force=True,
                    )
                called = [item for item in result["calls"] if item.get("status") == "called"]
                self.assertEqual(len(called), 1)
                mock_call.assert_called_once()

                with patch("slot_dispatch_service.tms_database", db):
                    second = await service.run_auto_dispatch(
                        forecasts=forecasts,
                        reference=reference,
                        voice_call_fn=mock_call,
                        force=True,
                    )
                skipped = [
                    item
                    for item in second["calls"]
                    if item.get("status") in {"skipped_booking_active", "skipped_booking_answered"}
                ]
                self.assertTrue(skipped)
                self.assertEqual(mock_call.call_count, 1)

        import asyncio

        asyncio.run(_run())

    def test_skips_non_at_risk_slot(self) -> None:
        async def _run() -> None:
            forecasts = [
                {
                    "corridor_id": "trasa_sucharskiego",
                    "corridor_name": "Trasa Sucharskiego",
                    "port_id": "gdynia",
                    "horizon_minutes": 60,
                    "predicted_delay_sec": 900,
                    "method": "ml_historical",
                }
            ]
            mock_call = AsyncMock(return_value={"call_sid": "CA-test", "strategy": "twilio_say"})
            reference = datetime(2026, 6, 23, 6, 0, tzinfo=LOCAL_TZ).astimezone(timezone.utc)
            plan = self.service.build_dispatch_plan(forecasts=forecasts, reference=reference)
            for alert in plan["alerts"]:
                alert["slot"] = {**alert["slot"], "status": "confirmed"}

            with patch.object(self.service, "build_dispatch_plan", return_value=plan):
                result = await self.service.run_auto_dispatch(
                    forecasts=forecasts,
                    reference=reference,
                    voice_call_fn=mock_call,
                    force=True,
                )
            skipped = [item for item in result["calls"] if item.get("status") == "skipped_not_at_risk"]
            self.assertTrue(skipped)
            mock_call.assert_not_called()

        import asyncio

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
