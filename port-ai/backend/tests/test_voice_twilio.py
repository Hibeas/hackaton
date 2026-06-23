"""Twilio call status mapping and tms_slot_calls updates."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from tms.database import TmsDatabase
from voice_call_service import apply_twilio_call_status_update, map_twilio_call_status


class TwilioStatusMappingTests(unittest.TestCase):
    def test_in_progress_maps_to_answered(self) -> None:
        self.assertEqual(map_twilio_call_status("in-progress"), "answered")

    def test_completed_with_duration_maps_to_answered(self) -> None:
        self.assertEqual(map_twilio_call_status("completed", duration_sec=12), "answered")

    def test_completed_zero_duration_no_update(self) -> None:
        self.assertIsNone(map_twilio_call_status("completed", duration_sec=0))

    def test_no_answer_maps_to_failed(self) -> None:
        self.assertEqual(map_twilio_call_status("no-answer"), "failed")


class TwilioSlotCallUpdateTests(unittest.TestCase):
    def test_webhook_marks_call_answered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = TmsDatabase(db_path=Path(tmp) / "tms_test.db")
            db.record_slot_call(
                provider_id="mock_msc",
                booking_ref="MSC-BKG-TEST",
                slot_id="SLOT-TEST",
                spedition_id="SPD-TEST",
                phone_e164="+48123456789",
                call_sid="CA-test-sid",
                call_status="initiated",
            )
            with patch("tms.database.tms_database", db):
                result = apply_twilio_call_status_update(
                    call_sid="CA-test-sid",
                    twilio_status="in-progress",
                )
            self.assertIsNotNone(result)
            assert result is not None
            self.assertTrue(result["updated"])
            self.assertEqual(result["call_status"], "answered")
            self.assertTrue(db.booking_has_answered_call("MSC-BKG-TEST"))

    def test_second_answered_blocked_for_same_booking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = TmsDatabase(db_path=Path(tmp) / "tms_test.db")
            db.record_slot_call(
                provider_id="mock_msc",
                booking_ref="MSC-BKG-DUP",
                slot_id="SLOT-B",
                spedition_id="SPD-B",
                phone_e164="+48222222222",
                call_sid="CA-second",
                call_status="initiated",
            )
            with patch.object(db, "booking_has_answered_call", return_value=True):
                result = db.update_slot_call_from_twilio(
                    call_sid="CA-second",
                    call_status="answered",
                    twilio_status="in-progress",
                )
            self.assertIsNotNone(result)
            assert result is not None
            self.assertEqual(result["call_status"], "failed")
            self.assertEqual(result.get("note"), "booking_already_answered")


if __name__ == "__main__":
    unittest.main()
