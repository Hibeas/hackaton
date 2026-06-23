"""Mock MSC carrier TMS — reads slot/spedition data from TmsDatabase."""

from __future__ import annotations

from datetime import date, datetime

from tms.canonical import CanonicalSlot, CanonicalSpedition, CarrierInfo
from tms.database import TmsDatabase, tms_database
from tms.providers.base import CarrierTmsProvider


class MockMscTmsProvider(CarrierTmsProvider):
    provider_id = "mock_msc"

    def __init__(self, database: TmsDatabase | None = None) -> None:
        self._db = database or tms_database

    def carrier_info(self) -> CarrierInfo:
        info = self._db.get_carrier(self.provider_id)
        if info is None:
            return CarrierInfo(
                provider_id=self.provider_id,
                display_name="Mock MSC Gate TMS",
                adapter="mock_msc_v1",
                active=True,
            )
        return info

    def fetch_slots(
        self,
        *,
        day: date,
        terminal_codes: list[str] | None = None,
        reference: datetime | None = None,
    ) -> list[CanonicalSlot]:
        templates = self._db.fetch_slot_templates(
            self.provider_id,
            terminal_codes=terminal_codes,
        )
        slots = [self._db.materialize_slot(self.provider_id, template, day) for template in templates]
        slots.sort(key=lambda item: item["window_start"])
        return slots

    def fetch_speditions(self, *, slot_ids: list[str] | None = None) -> list[CanonicalSpedition]:
        return self._db.fetch_speditions(self.provider_id, slot_ids=slot_ids)
