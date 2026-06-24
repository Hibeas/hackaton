"""Tests for cancel/reschedule booking actions."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from tms.bookings_service import cancel_my_booking, ensure_placeholder_bookings, reschedule_my_booking
from tms.database import TmsDatabase

LOCAL_TZ = ZoneInfo("Europe/Warsaw")


class BookingActionsTests(unittest.TestCase):
    def test_cancel_and_reschedule_owned_booking(self) -> None:
        user_id = "user-actions-001"
        with tempfile.TemporaryDirectory() as tmp:
            db = TmsDatabase(db_path=Path(tmp) / "tms_actions.db")
            reference = datetime(2026, 6, 24, 8, 0, tzinfo=LOCAL_TZ).astimezone(timezone.utc)
            with patch("tms.bookings_service.tms_database", db):
                created = ensure_placeholder_bookings(
                    user_id,
                    phone_e164="+48111111111",
                    contact_name="Jan",
                    reference=reference,
                )
                self.assertEqual(created, 4)

                templates = db.fetch_bookings_for_user(user_id)
                slot = templates[0]
                provider_id = str(slot["provider_id"])
                slot_id = str(slot["slot_id"])
                original_start = db._parse_optional_timestamp(slot.get("window_start_at"))
                assert original_start is not None

                shifted = reschedule_my_booking(
                    user_id,
                    provider_id=provider_id,
                    slot_id=slot_id,
                    offset_minutes=60,
                )
                self.assertEqual(shifted["slot_id"], slot_id)
                self.assertIn("window_local", shifted)

                updated = db.get_owned_slot_template(provider_id, slot_id, user_id)
                assert updated is not None
                new_start = db._parse_optional_timestamp(updated.get("window_start_at"))
                assert new_start is not None
                self.assertEqual(new_start, original_start + timedelta(hours=1))

                target = datetime(2026, 6, 24, 14, 30, tzinfo=LOCAL_TZ).astimezone(timezone.utc)
                absolute = reschedule_my_booking(
                    user_id,
                    provider_id=provider_id,
                    slot_id=slot_id,
                    window_start_at=target,
                )
                self.assertEqual(absolute["slot_id"], slot_id)

                updated_absolute = db.get_owned_slot_template(provider_id, slot_id, user_id)
                assert updated_absolute is not None
                absolute_start = db._parse_optional_timestamp(updated_absolute.get("window_start_at"))
                assert absolute_start is not None
                self.assertEqual(absolute_start, target)

                cancelled = cancel_my_booking(user_id, provider_id=provider_id, slot_id=slot_id)
                self.assertTrue(cancelled["ok"])
                updated_after_cancel = db.get_owned_slot_template(provider_id, slot_id, user_id)
                assert updated_after_cancel is not None
                self.assertEqual(updated_after_cancel.get("status"), "cancelled")


if __name__ == "__main__":
    unittest.main()
