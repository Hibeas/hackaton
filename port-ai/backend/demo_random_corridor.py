"""Shared helpers for random demo corridor selection."""

from __future__ import annotations

import random
from typing import Any

from corridor_service import load_corridor_config


def list_approach_corridors(*, port_id: str | None = None) -> list[dict[str, Any]]:
    config = load_corridor_config()
    corridors: list[dict[str, Any]] = []
    for port in config.get("ports", []):
        if port_id and str(port.get("id")) != port_id:
            continue
        for corridor in port.get("corridors", []):
            if str(corridor.get("geofence_type") or "") != "APPROACH_CORRIDOR":
                continue
            corridors.append(
                {
                    "corridor_id": str(corridor["id"]),
                    "corridor_name": str(corridor.get("name") or corridor["id"]),
                    "port_id": str(port["id"]),
                    "port_name": str(port.get("name") or port["id"]),
                }
            )
    return corridors


def pick_random_approach_corridor(*, port_id: str | None = None) -> dict[str, Any]:
    candidates = list_approach_corridors(port_id=port_id)
    if not candidates:
        raise ValueError("no_approach_corridors")
    return random.choice(candidates)
