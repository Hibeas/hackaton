"""Unified TMS store — aggregates carrier providers into canonical records."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from tms.canonical import CanonicalSlot, CanonicalSpedition, CarrierInfo
from tms.database import tms_database
from tms.providers.base import CarrierTmsProvider
from tms.providers.mock_msc import MockMscTmsProvider

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
CORRIDOR_TERMINAL_MAP_PATH = BASE_DIR / "data" / "port" / "corridor_terminal_map.json"
TERMINALS_PATH = BASE_DIR / "data" / "port" / "terminals.json"


class TmsStore:
    def __init__(self, providers: list[CarrierTmsProvider] | None = None) -> None:
        self._providers = providers or [MockMscTmsProvider()]
        self.updated_at: datetime | None = None

    def list_providers(self) -> list[CarrierInfo]:
        return [provider.carrier_info() for provider in self._providers if provider.carrier_info()["active"]]

    def refresh(self) -> None:
        self.updated_at = datetime.now(timezone.utc)
        logger.info("TMS store refreshed (%s providers)", len(self._providers))

    def slots_for_day(
        self,
        day: date | None = None,
        *,
        terminal_codes: list[str] | None = None,
    ) -> list[CanonicalSlot]:
        target = day or datetime.now(timezone.utc).date()
        slots: list[CanonicalSlot] = []
        for provider in self._providers:
            if not provider.carrier_info()["active"]:
                continue
            slots.extend(provider.fetch_slots(day=target, terminal_codes=terminal_codes))
        return slots

    def speditions_for_slots(self, slot_ids: list[str]) -> list[CanonicalSpedition]:
        if not slot_ids:
            return []
        results: list[CanonicalSpedition] = []
        for provider in self._providers:
            if not provider.carrier_info()["active"]:
                continue
            results.extend(provider.fetch_speditions(slot_ids=slot_ids))
        return results

    def corridor_terminal_map(self) -> dict[str, list[str]]:
        if not CORRIDOR_TERMINAL_MAP_PATH.is_file():
            return {}
        with CORRIDOR_TERMINAL_MAP_PATH.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        mapping: dict[str, list[str]] = {}
        for item in payload.get("mappings") or []:
            mapping[str(item["corridor_id"])] = [str(code) for code in (item.get("terminals") or [])]
        return mapping

    def terminal_labels(self) -> dict[str, str]:
        if not TERMINALS_PATH.is_file():
            return {}
        with TERMINALS_PATH.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        labels: dict[str, str] = {}
        for code, meta in (payload.get("terminals") or {}).items():
            labels[str(code)] = str(meta.get("label") or code)
        return labels

    def snapshot(self, day: date | None = None) -> dict[str, Any]:
        target_day = day or datetime.now(timezone.utc).date()
        slots = self.slots_for_day(target_day)
        speditions = self.speditions_for_slots([slot["slot_id"] for slot in slots])
        return {
            "day": target_day.isoformat(),
            "providers": self.list_providers(),
            "slots": slots,
            "speditions": speditions,
            "database": tms_database.backend_name,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


tms_store = TmsStore()
