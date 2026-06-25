"""Synthetic crowd incidents + heatmap points along a corridor (demo / backtest viz)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from corridor_service import find_corridor_by_id
from tomtom_service import build_heatmap_points, derive_status, infer_city


def _polygon_line_coords(corridor: dict[str, Any]) -> list[list[float]]:
    """LineString [lon, lat] along corridor polygon or bbox diagonal."""
    polygon = corridor.get("polygon") or []
    if len(polygon) >= 2:
        return [[float(p[1]), float(p[0])] for p in polygon]

    bbox = corridor.get("bbox") or {}
    min_lat = float(bbox.get("min_lat", 0))
    max_lat = float(bbox.get("max_lat", 0))
    min_lon = float(bbox.get("min_lon", 0))
    max_lon = float(bbox.get("max_lon", 0))
    return [
        [min_lon, min_lat],
        [max_lon, max_lat],
    ]


def _segment_line(
    coords: list[list[float]],
    start_ratio: float,
    end_ratio: float,
) -> list[list[float]]:
    if len(coords) < 2:
        return coords
    total = len(coords) - 1
    start_idx = int(start_ratio * total)
    end_idx = max(start_idx + 1, int(end_ratio * total))
    end_idx = min(end_idx, total)
    segment = coords[start_idx : end_idx + 1]
    return segment if len(segment) >= 2 else [coords[start_idx], coords[min(start_idx + 1, total)]]


def build_synthetic_crowd_events(
    corridor: dict[str, Any],
    *,
    peak_delay_sec: int = 960,
    start_delay_sec: int = 120,
    incident_count: int = 6,
    primary_reason: str | None = None,
    demo_tag: str = "demo_crowd",
) -> list[dict[str, Any]]:
    """TomTom-shaped incidents with rising delay along the corridor spine."""
    spine = _polygon_line_coords(corridor)
    city = str(corridor.get("city") or infer_city(spine[0][1], spine[0][0]))
    corridor_name = str(corridor.get("name") or corridor.get("id") or "Korytarz")
    now = datetime.now(timezone.utc).isoformat()
    reason = primary_reason or "Sztuczny tłum (demo backtest)"
    events: list[dict[str, Any]] = []

    for index in range(incident_count):
        ratio = index / max(1, incident_count - 1)
        start_r = max(0.0, ratio - 0.12)
        end_r = min(1.0, ratio + 0.18)
        line = _segment_line(spine, start_r, end_r)
        mid = line[len(line) // 2]
        lon, lat = float(mid[0]), float(mid[1])

        delay_sec = int(round(start_delay_sec + (peak_delay_sec - start_delay_sec) * ratio))
        magnitude = min(4, 2 + index)
        icon_category = 6  # Korek
        status = derive_status(delay_sec, magnitude, icon_category)

        events.append(
            {
                "event_id": f"synthetic_crowd_{corridor['id']}_{index}",
                "record_kind": "incident",
                "data_tier": "primary",
                "entity_id": f"demo-crowd-{index}",
                "city": city,
                "source_type": "tomtom_traffic",
                "timestamp": now,
                "location": {
                    "lat": lat,
                    "lon": lon,
                    "road_name": f"{corridor_name} (demo tłum #{index + 1})",
                },
                "geometry": {"type": "LineString", "coordinates": line},
                "metrics": {
                    "delay_sec": delay_sec,
                    "length_m": 400 + index * 120,
                    "icon_category": icon_category,
                    "category_label": "Korek",
                    "primary_reason": reason,
                    "magnitude": magnitude,
                    "time_validity": "present",
                    "speed_kmh": 0,
                    "intensity_vph": None,
                },
                "status": status,
                demo_tag: True,
            }
        )

    return events


def build_crowd_map_payload(
    corridor_id: str,
    *,
    peak_delay_sec: int = 960,
    start_delay_sec: int = 120,
    incident_count: int = 6,
    primary_reason: str | None = None,
    demo_tag: str = "demo_crowd",
) -> dict[str, Any]:
    _port, corridor = find_corridor_by_id(corridor_id)
    events = build_synthetic_crowd_events(
        corridor,
        peak_delay_sec=peak_delay_sec,
        start_delay_sec=start_delay_sec,
        incident_count=incident_count,
        primary_reason=primary_reason,
        demo_tag=demo_tag,
    )
    points = build_heatmap_points(events)
    return {
        "corridor_id": corridor_id,
        "corridor_name": corridor.get("name"),
        "peak_delay_sec": peak_delay_sec,
        "primary": {
            "source": "synthetic_crowd",
            "events": events,
            "incident_count": len(events),
        },
        "heatmap": {
            "source": "synthetic_crowd",
            "points": points,
            "flow_tile_url": None,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
