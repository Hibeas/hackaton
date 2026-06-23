"""Carrier TMS provider adapter interface (FireTMS-style plug-in point)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime

from tms.canonical import CanonicalSlot, CanonicalSpedition, CarrierInfo


class CarrierTmsProvider(ABC):
    """Pull carrier-native data and map it to canonical Port-AI TMS types."""

    @property
    @abstractmethod
    def provider_id(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def carrier_info(self) -> CarrierInfo:
        raise NotImplementedError

    @abstractmethod
    def fetch_slots(
        self,
        *,
        day: date,
        terminal_codes: list[str] | None = None,
        reference: datetime | None = None,
    ) -> list[CanonicalSlot]:
        raise NotImplementedError

    @abstractmethod
    def fetch_speditions(self, *, slot_ids: list[str] | None = None) -> list[CanonicalSpedition]:
        raise NotImplementedError
