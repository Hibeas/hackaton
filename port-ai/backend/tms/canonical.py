"""Internal canonical TMS types (provider-agnostic)."""

from __future__ import annotations

from typing import Any, TypedDict


class CanonicalSlot(TypedDict):
    slot_id: str
    provider_id: str
    terminal_code: str
    port_id: str
    window_start: str
    window_end: str
    container_count: int
    booking_ref: str
    status: str
    external_ref: str
    corridor_ids: list[str]


class CanonicalSpedition(TypedDict):
    spedition_id: str
    provider_id: str
    company_name: str
    contact_name: str
    phone_e164: str
    slot_ids: list[str]
    email: str | None


class CarrierInfo(TypedDict):
    provider_id: str
    display_name: str
    adapter: str
    active: bool


def slot_to_dict(slot: CanonicalSlot) -> dict[str, Any]:
    return dict(slot)


def spedition_to_dict(spedition: CanonicalSpedition) -> dict[str, Any]:
    return dict(spedition)
