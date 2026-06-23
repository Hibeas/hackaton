"""Tests for TMS mock store and slot dispatch orchestration."""

from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from slot_dispatch_service import SlotDispatchService, SLOT_DISPATCH_MIN_DELAY_SEC
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


if __name__ == "__main__":
    unittest.main()
