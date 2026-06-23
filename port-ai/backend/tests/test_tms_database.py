"""TMS database layer tests."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date

from tms.database import TmsDatabase
from tms.providers.mock_msc import MockMscTmsProvider


class TmsDatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._prev_db_url = os.environ.pop("DATABASE_URL", None)
        self.db = TmsDatabase(db_path=os.path.join(self._tmpdir.name, "tms.db"))

    def tearDown(self) -> None:
        if self._prev_db_url is not None:
            os.environ["DATABASE_URL"] = self._prev_db_url
        self._tmpdir.cleanup()

    def test_seeds_mock_msc_carrier(self) -> None:
        carrier = self.db.get_carrier("mock_msc")
        self.assertIsNotNone(carrier)
        assert carrier is not None
        self.assertEqual(carrier["display_name"], "Mock MSC Gate TMS")

    def test_slot_templates_and_speditions_with_phones(self) -> None:
        templates = self.db.fetch_slot_templates("mock_msc")
        self.assertGreaterEqual(len(templates), 6)
        speditions = self.db.fetch_speditions("mock_msc", slot_ids=["SLOT-DCT-0800"])
        self.assertEqual(len(speditions), 1)
        self.assertTrue(speditions[0]["phone_e164"].startswith("+"))

    def test_provider_reads_from_database(self) -> None:
        provider = MockMscTmsProvider(database=self.db)
        slots = provider.fetch_slots(day=date(2026, 6, 23))
        self.assertGreater(len(slots), 0)
        speditions = provider.fetch_speditions(slot_ids=[slots[0]["slot_id"]])
        self.assertGreater(len(speditions), 0)


if __name__ == "__main__":
    unittest.main()
