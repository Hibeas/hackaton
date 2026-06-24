"""Tests for user bookings (awizacje) from TMS."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from tms.bookings_service import build_my_bookings
from tms.database import TmsDatabase

LOCAL_TZ = ZoneInfo("Europe/Warsaw")


class MyBookingsTests(unittest.TestCase):
    def test_bookings_for_user(self) -> None:
        user_id = "user-test-001"
        other_user_id = "user-test-002"
        with tempfile.TemporaryDirectory() as tmp:
            db = TmsDatabase(db_path=Path(tmp) / "tms_test.db")
            db.upsert_carrier(
                provider_id="mock_msc",
                display_name="Mock MSC",
                adapter="mock_msc_v1",
                active=True,
                description_pl="test",
            )
            db.upsert_slot_template(
                "mock_msc",
                {
                    "slot_id": "SLOT-TEST-0800",
                    "terminal_code": "GCT",
                    "port_id": "gdynia",
                    "start_hour": 8,
                    "start_minute": 0,
                    "duration_minutes": 30,
                    "container_count": 2,
                    "booking_ref": "MSC-TEST-001",
                    "status": "at_risk",
                    "corridor_ids": ["ul_polska"],
                    "owner_user_id": user_id,
                },
            )
            db.upsert_slot_template(
                "mock_msc",
                {
                    "slot_id": "SLOT-TEST-0900",
                    "terminal_code": "GCT",
                    "port_id": "gdynia",
                    "start_hour": 9,
                    "start_minute": 0,
                    "duration_minutes": 30,
                    "container_count": 1,
                    "booking_ref": "MSC-TEST-002",
                    "status": "confirmed",
                    "corridor_ids": ["ul_polska"],
                    "owner_user_id": other_user_id,
                },
            )
            db.clear_spedition_links_for_slot("mock_msc", "SLOT-TEST-0800")
            db.upsert_spedition(
                "mock_msc",
                {
                    "spedition_id": "SPD-TEST",
                    "company_name": "Test Sped",
                    "contact_name": "Jan",
                    "phone_e164": "+48123456789",
                    "email": "jan@test.pl",
                },
                ["SLOT-TEST-0800"],
            )
            db.clear_spedition_links_for_slot("mock_msc", "SLOT-TEST-0900")
            db.upsert_spedition(
                "mock_msc",
                {
                    "spedition_id": "SPD-OTHER",
                    "company_name": "Other Sped",
                    "contact_name": "Anna",
                    "phone_e164": "+48123456789",
                    "email": "anna@test.pl",
                },
                ["SLOT-TEST-0900"],
            )

            reference = datetime(2026, 6, 24, 6, 0, tzinfo=LOCAL_TZ).astimezone(timezone.utc)
            with patch("tms.bookings_service.tms_database", db):
                payload = build_my_bookings(user_id, reference=reference, seed_placeholders=False)
                other_payload = build_my_bookings(other_user_id, reference=reference, seed_placeholders=False)
            self.assertEqual(payload["total"], 1)
            self.assertEqual(payload["bookings"][0]["booking_ref"], "MSC-TEST-001")
            self.assertEqual(other_payload["total"], 1)
            self.assertEqual(other_payload["bookings"][0]["booking_ref"], "MSC-TEST-002")
            # Slot at 08:00 with reference 06:00 — DB at_risk is shown until window ends
            self.assertEqual(payload["bookings"][0]["status"], "at_risk")


if __name__ == "__main__":
    unittest.main()
