"""
Corridor mapping — assigns TomTom (primary) and ZTM (context) data to port access roads.

Each corridor is a bbox around a known approach route. Observations are aggregated
per corridor for the anomaly engine time-series store.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from port_demand import PortDemandBaseline, current_port_time

logger = logging.getLogger(__name__)

SERVICE_DIR = os.path.dirname(os.path.abspath(__file__))
CORRIDORS_PATH = os.path.join(SERVICE_DIR, "corridors.json")

CONGESTED_STATUSES = {"CONGESTION", "CRITICAL"}

# Severity multiplier modifiers by geofence role (MVP business weighting).
GEOFENCE_TYPE_BOOST: dict[str, float] = {
    "BOTTLENECK": 1.05,
    "GATE_ZONE": 1.05,
    "CRITICAL_INFRASTRUCTURE": 1.05,
    "APPROACH_CORRIDOR": 1.0,
    "PORT_ACCESS": 0.98,
    "BUFFER_ZONE": 0.92,
}


def corridor_priority_multiplier(corridor: dict[str, Any]) -> float:
    """Map logistics_weight (1–10) and geofence type to a 0.1–1.05 severity multiplier."""
    if corridor.get("logistics_weight") is not None:
        base = float(corridor["logistics_weight"]) / 10.0
    else:
        base = float(corridor.get("priority_weight", 0.8))

    type_boost = GEOFENCE_TYPE_BOOST.get(str(corridor.get("geofence_type") or ""), 1.0)
    return round(min(1.05, base * type_boost), 3)


def load_corridor_config() -> dict[str, Any]:
    with open(CORRIDORS_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_config(config: dict[str, Any]) -> None:
    with open(CORRIDORS_PATH, "w", encoding="utf-8") as handle:
        json.dump(config, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _apply_geometry(
    target: dict[str, Any],
    bbox: dict[str, float],
    polygon: list[list[float]] | None = None,
) -> None:
    target["bbox"] = {
        "min_lat": float(bbox["min_lat"]),
        "max_lat": float(bbox["max_lat"]),
        "min_lon": float(bbox["min_lon"]),
        "max_lon": float(bbox["max_lon"]),
    }
    if polygon and len(polygon) >= 3:
        target["polygon"] = [[float(p[0]), float(p[1])] for p in polygon]
    elif "polygon" in target:
        del target["polygon"]


def _find_port(config: dict[str, Any], port_id: str) -> dict[str, Any] | None:
    for port in config["ports"]:
        if port["id"] == port_id:
            return port
    return None


def _find_corridor(config: dict[str, Any], corridor_id: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    for port in config["ports"]:
        for corridor in port["corridors"]:
            if corridor["id"] == corridor_id:
                return port, corridor
    return None


def find_corridor_by_id(corridor_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve port + corridor metadata from corridors.json."""
    found = _find_corridor(load_corridor_config(), corridor_id)
    if not found:
        raise ValueError(f"corridor_not_found:{corridor_id}")
    return found


def update_port_geometry(
    port_id: str,
    bbox: dict[str, float],
    polygon: list[list[float]] | None = None,
) -> dict[str, Any]:
    config = load_corridor_config()
    port = _find_port(config, port_id)
    if not port:
        raise ValueError(f"Port not found: {port_id}")

    geofence = port.setdefault("geofence", {})
    _apply_geometry(geofence, bbox, polygon)
    _write_config(config)
    logger.info("Updated geofence for port %s", port_id)
    return config


def update_corridor_geometry(
    corridor_id: str,
    bbox: dict[str, float],
    polygon: list[list[float]] | None = None,
) -> dict[str, Any]:
    """Persist bbox (and optional polygon vertices) for a corridor in corridors.json."""
    config = load_corridor_config()
    found = _find_corridor(config, corridor_id)
    if not found:
        raise ValueError(f"Corridor not found: {corridor_id}")

    _, corridor = found
    _apply_geometry(corridor, bbox, polygon)
    _write_config(config)
    logger.info("Updated geometry for corridor %s", corridor_id)
    return config


def create_corridor(port_id: str, corridor: dict[str, Any]) -> dict[str, Any]:
    config = load_corridor_config()
    port = _find_port(config, port_id)
    if not port:
        raise ValueError(f"Port not found: {port_id}")

    corridor_id = str(corridor["id"]).strip()
    if not corridor_id:
        raise ValueError("Corridor id is required")

    for existing_port in config["ports"]:
        for existing in existing_port["corridors"]:
            if existing["id"] == corridor_id:
                raise ValueError(f"Corridor id already exists: {corridor_id}")

    logistics_weight = int(corridor.get("logistics_weight") or 7)
    entry = {
        "id": corridor_id,
        "name": str(corridor.get("name") or corridor_id),
        "city": str(corridor.get("city") or port.get("name", "")),
        "geofence_type": corridor.get("geofence_type") or "APPROACH_CORRIDOR",
        "business_priority": corridor.get("business_priority") or "HIGH",
        "logistics_weight": logistics_weight,
        "priority_weight": round(logistics_weight / 10.0, 2),
        "impacts_port_access": bool(corridor.get("impacts_port_access", True)),
        "bbox": corridor["bbox"],
        "terminals": corridor.get("terminals") or port.get("terminals") or [],
    }
    if corridor.get("polygon"):
        entry["polygon"] = corridor["polygon"]

    port["corridors"].append(entry)
    _write_config(config)
    logger.info("Created corridor %s under port %s", corridor_id, port_id)
    return config


def update_corridor_metadata(corridor_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    config = load_corridor_config()
    found = _find_corridor(config, corridor_id)
    if not found:
        raise ValueError(f"Corridor not found: {corridor_id}")

    _, corridor = found
    allowed = (
        "name",
        "city",
        "geofence_type",
        "business_priority",
        "logistics_weight",
        "impacts_port_access",
        "terminals",
    )
    for key in allowed:
        if key in updates and updates[key] is not None:
            corridor[key] = updates[key]

    if "logistics_weight" in updates and updates["logistics_weight"] is not None:
        corridor["priority_weight"] = round(float(corridor["logistics_weight"]) / 10.0, 2)

    _write_config(config)
    logger.info("Updated metadata for corridor %s", corridor_id)
    return config


def delete_corridor(corridor_id: str) -> dict[str, Any]:
    config = load_corridor_config()
    for port in config["ports"]:
        before = len(port["corridors"])
        port["corridors"] = [item for item in port["corridors"] if item["id"] != corridor_id]
        if len(port["corridors"]) < before:
            _write_config(config)
            logger.info("Deleted corridor %s", corridor_id)
            return config

    raise ValueError(f"Corridor not found: {corridor_id}")


def _point_in_bbox(lat: float, lon: float, bbox: dict[str, float]) -> bool:
    return (
        bbox["min_lat"] <= lat <= bbox["max_lat"]
        and bbox["min_lon"] <= lon <= bbox["max_lon"]
    )


def _point_in_polygon(lat: float, lon: float, polygon: list[list[float]]) -> bool:
    """Ray casting; polygon vertices are [lat, lon]."""
    if len(polygon) < 3:
        return False
    inside = False
    count = len(polygon)
    j = count - 1
    for i in range(count):
        yi, xi = float(polygon[i][0]), float(polygon[i][1])
        yj, xj = float(polygon[j][0]), float(polygon[j][1])
        if ((yi > lat) != (yj > lat)) and (
            lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-15) + xi
        ):
            inside = not inside
        j = i
    return inside


def _geometry_hits_polygon(geometry: dict[str, Any] | None, polygon: list[list[float]]) -> bool:
    if not geometry:
        return False
    coords = geometry.get("coordinates")
    if not coords:
        return False
    if geometry.get("type") == "Point" and len(coords) >= 2:
        return _point_in_polygon(float(coords[1]), float(coords[0]), polygon)
    if geometry.get("type") == "LineString":
        for point in coords:
            if len(point) >= 2 and _point_in_polygon(float(point[1]), float(point[0]), polygon):
                return True
    return False


def _geometry_hits_bbox(geometry: dict[str, Any] | None, bbox: dict[str, float]) -> bool:
    if not geometry:
        return False
    coords = geometry.get("coordinates")
    if not coords:
        return False
    if geometry.get("type") == "Point":
        lon, lat = coords
        return _point_in_bbox(float(lat), float(lon), bbox)
    if geometry.get("type") == "LineString":
        for point in coords:
            if len(point) >= 2 and _point_in_bbox(float(point[1]), float(point[0]), bbox):
                return True
    return False


def _event_in_bbox(event: dict[str, Any], bbox: dict[str, float]) -> bool:
    location = event.get("location") or {}
    lat = location.get("lat")
    lon = location.get("lon")
    if lat is not None and lon is not None and _point_in_bbox(float(lat), float(lon), bbox):
        return True
    return _geometry_hits_bbox(event.get("geometry"), bbox)


def _event_in_polygon(event: dict[str, Any], polygon: list[list[float]]) -> bool:
    location = event.get("location") or {}
    lat = location.get("lat")
    lon = location.get("lon")
    if lat is not None and lon is not None and _point_in_polygon(float(lat), float(lon), polygon):
        return True
    return _geometry_hits_polygon(event.get("geometry"), polygon)


def _event_in_corridor(event: dict[str, Any], corridor: dict[str, Any]) -> bool:
    """Prefer calibrated polygon; fall back to axis-aligned bbox."""
    polygon = corridor.get("polygon")
    if polygon and len(polygon) >= 3:
        return _event_in_polygon(event, polygon)
    return _event_in_bbox(event, corridor["bbox"])


def _avg_speed(context_events: list[dict[str, Any]]) -> float | None:
    """GPS speeds from ZTM vehicles only — not loop intensity estimates."""
    speeds: list[float] = []
    for event in context_events:
        if event.get("record_kind") != "vehicle":
            continue
        metrics = event.get("metrics") or {}
        if metrics.get("is_bus_stop"):
            continue
        speed = metrics.get("speed_kmh")
        if speed is not None and float(speed) >= 0:
            speeds.append(float(speed))
    if not speeds:
        return None
    return round(sum(speeds) / len(speeds), 1)


def _congestion_ratio(context_events: list[dict[str, Any]]) -> float | None:
    considered = 0
    congested = 0
    for event in context_events:
        metrics = event.get("metrics") or {}
        if event.get("record_kind") == "vehicle" and metrics.get("is_bus_stop"):
            continue
        considered += 1
        if event.get("status") in CONGESTED_STATUSES:
            congested += 1
    if not considered:
        return None
    return round(congested / considered, 3)


def _avg_intensity(context_events: list[dict[str, Any]]) -> float | None:
    values: list[float] = []
    for event in context_events:
        if event.get("record_kind") != "road_segment":
            continue
        intensity = (event.get("metrics") or {}).get("intensity_vph")
        if intensity is not None:
            values.append(float(intensity))
    if not values:
        return None
    return round(sum(values) / len(values), 1)


def _demand_ratio(baseline: PortDemandBaseline, terminals: list[str], now: datetime) -> float | None:
    if not baseline.is_loaded or not terminals:
        return None
    dow = now.weekday()
    hour = now.hour
    expected = sum(baseline.expected_terminal_moves(terminal, dow, hour) for terminal in terminals)
    peak = sum(baseline.terminal_peak(terminal) for terminal in terminals)
    if peak <= 0:
        return None
    return round(expected / peak, 3)


def build_corridor_snapshots(
    primary_events: list[dict[str, Any]],
    context_events: list[dict[str, Any]],
    baseline: PortDemandBaseline,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    reference = current_port_time(now)
    config = load_corridor_config()
    snapshots: list[dict[str, Any]] = []

    for port in config["ports"]:
        for corridor in port["corridors"]:
            corridor_primary = [event for event in primary_events if _event_in_corridor(event, corridor)]
            corridor_context = [event for event in context_events if _event_in_corridor(event, corridor)]

            delays = [
                int((event.get("metrics") or {}).get("delay_sec") or 0)
                for event in corridor_primary
            ]
            causes: list[str] = []
            top_event_metrics: dict[str, Any] = {}
            sorted_primary = sorted(
                corridor_primary,
                key=lambda item: int((item.get("metrics") or {}).get("delay_sec") or 0),
                reverse=True,
            )
            if sorted_primary:
                top_event_metrics = sorted_primary[0].get("metrics") or {}
            for event in sorted_primary[:3]:
                metrics = event.get("metrics") or {}
                reason = metrics.get("primary_reason") or metrics.get("category_label") or "?"
                road = (event.get("location") or {}).get("road_name") or "?"
                causes.append(f"{reason} ({road})")

            terminals = corridor.get("terminals") or port.get("terminals") or []
            priority = corridor_priority_multiplier(corridor)
            snapshots.append(
                {
                    "corridor_id": corridor["id"],
                    "port_id": port["id"],
                    "port_name": port["name"],
                    "corridor_name": corridor["name"],
                    "city": corridor.get("city"),
                    "geofence_type": corridor.get("geofence_type"),
                    "business_priority": corridor.get("business_priority"),
                    "logistics_weight": corridor.get("logistics_weight"),
                    "impacts_port_access": corridor.get("impacts_port_access", True),
                    "priority_weight": priority,
                    "terminals": terminals,
                    "timestamp": reference.astimezone(timezone.utc).isoformat(),
                    "metrics": {
                        "avg_speed_kmh": _avg_speed(corridor_context),
                        "incident_count": len(corridor_primary),
                        "total_delay_sec": sum(delays),
                        "max_delay_sec": max(delays) if delays else 0,
                        "congestion_ratio": _congestion_ratio(corridor_context),
                        "avg_intensity_vph": _avg_intensity(corridor_context),
                        "demand_ratio": _demand_ratio(baseline, terminals, reference),
                        "top_incident_causes": causes,
                        "primary_incident_category": int(
                            top_event_metrics.get("icon_category") or 0
                        ),
                    },
                }
            )

    return snapshots
