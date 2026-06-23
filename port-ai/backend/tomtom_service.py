"""
TomTom Traffic API service — primary live data source.

Fetches road incidents (present + planned) and normalizes them into the unified
event schema consumed by the map and anomaly classifier. ZTM municipal feeds
are secondary context only; TomTom drives live congestion visibility and verdicts.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_default_tomtom_key = "Eeuz6XPvDckP0avEfM50keYMPdgsWmNG"
TOMTOM_API_KEY = (os.environ.get("TOMTOM_API_KEY") or "").strip() or _default_tomtom_key
TOMTOM_INCIDENTS_URL = "https://api.tomtom.com/traffic/services/5/incidentDetails"
REQUEST_TIMEOUT = 30.0

INCIDENT_FIELDS = (
    "{incidents{type,geometry{type,coordinates},properties{"
    "id,iconCategory,magnitudeOfDelay,events{description,code,iconCategory},"
    "startTime,endTime,from,to,length,delay,roadNumbers,timeValidity,"
    "probabilityOfOccurrence,numberOfReports,lastReportTime}}}"
)

BBOX_TROJMIASTO = "18.4000,54.3000,18.7500,54.6000"
BBOX_SZCZECIN = "14.4000,53.3500,14.7500,53.5500"
BBOX_SWINOUJSCIE = "14.2000,53.8800,14.3500,53.9500"

ICON_CATEGORY_PL: dict[int, str] = {
    0: "Nieznane",
    1: "Wypadek",
    2: "Mgła",
    3: "Niebezpieczne warunki",
    4: "Deszcz",
    5: "Gołoledź",
    6: "Korek",
    7: "Zamknięty pas",
    8: "Droga zamknięta",
    9: "Roboty drogowe",
    10: "Wiatr",
    11: "Powódź",
    14: "Unieruchomiony pojazd",
}

# Rough city assignment for incidents (centroid-based).
CITY_BOUNDS: dict[str, dict[str, float]] = {
    "Gdansk": {"min_lat": 54.30, "max_lat": 54.44, "min_lon": 18.55, "max_lon": 18.75},
    "Gdynia": {"min_lat": 54.44, "max_lat": 54.58, "min_lon": 18.40, "max_lon": 18.62},
    "Szczecin": {"min_lat": 53.35, "max_lat": 53.55, "min_lon": 14.40, "max_lon": 14.75},
}


def infer_city(lat: float, lon: float) -> str:
    for city, bounds in CITY_BOUNDS.items():
        if (
            bounds["min_lat"] <= lat <= bounds["max_lat"]
            and bounds["min_lon"] <= lon <= bounds["max_lon"]
        ):
            return city
    return "Trojmiasto"


def incident_centroid(incident: dict[str, Any]) -> tuple[float, float] | None:
    geometry = incident.get("geometry") or {}
    if geometry.get("type") == "Point":
        lon, lat = geometry["coordinates"]
        return float(lat), float(lon)
    if geometry.get("type") == "LineString":
        coords = geometry["coordinates"]
        if not coords:
            return None
        mid = coords[len(coords) // 2]
        return float(mid[1]), float(mid[0])
    return None


def normalize_geometry(geometry: dict[str, Any]) -> dict[str, Any] | None:
    geom_type = geometry.get("type")
    if geom_type == "Point":
        lon, lat = geometry["coordinates"]
        return {"type": "Point", "coordinates": [float(lon), float(lat)]}
    if geom_type == "LineString":
        coordinates = [
            [float(point[0]), float(point[1])]
            for point in geometry.get("coordinates") or []
            if isinstance(point, (list, tuple)) and len(point) >= 2
        ]
        if len(coordinates) < 2:
            return None
        return {"type": "LineString", "coordinates": coordinates}
    return None


def derive_status(delay_sec: int, magnitude: int, icon_category: int) -> str:
    if icon_category in (1, 8) or magnitude >= 4 or delay_sec >= 180:
        return "CRITICAL"
    if icon_category == 6 or magnitude >= 2 or delay_sec >= 45:
        return "CONGESTION"
    return "CONGESTION"


def incident_to_event(incident: dict[str, Any], time_validity: str) -> dict[str, Any] | None:
    props = incident.get("properties") or {}
    geometry = normalize_geometry(incident.get("geometry") or {})
    if geometry is None:
        return None

    centroid = incident_centroid(incident)
    if centroid is None:
        return None
    lat, lon = centroid

    events = props.get("events") or []
    event_texts = [
        event.get("description", "").strip()
        for event in events
        if event.get("description")
    ]
    icon_category = int(props.get("iconCategory") or 0)
    category_label = ICON_CATEGORY_PL.get(icon_category, f"kategoria {icon_category}")
    primary_reason = event_texts[0] if event_texts else category_label

    road_from = props.get("from") or "?"
    road_to = props.get("to") or "?"
    road_numbers = props.get("roadNumbers") or []
    road_name = ", ".join(road_numbers) if road_numbers else f"{road_from} → {road_to}"

    delay_sec = int(props.get("delay") or 0)
    magnitude = int(props.get("magnitudeOfDelay") or 0)
    incident_id = str(props.get("id") or id(incident))

    timestamp = props.get("lastReportTime") or props.get("startTime")
    if not timestamp:
        timestamp = datetime.now(timezone.utc).isoformat()

    return {
        "event_id": f"tomtom_{incident_id}",
        "record_kind": "incident",
        "data_tier": "primary",
        "entity_id": incident_id,
        "city": infer_city(lat, lon),
        "source_type": "tomtom_traffic",
        "timestamp": timestamp,
        "location": {"lat": lat, "lon": lon, "road_name": road_name},
        "geometry": geometry,
        "metrics": {
            "delay_sec": delay_sec,
            "length_m": int(props.get("length") or 0),
            "icon_category": icon_category,
            "category_label": category_label,
            "primary_reason": primary_reason,
            "magnitude": magnitude,
            "time_validity": time_validity,
            "probability": props.get("probabilityOfOccurrence"),
            "speed_kmh": 0,
            "intensity_vph": None,
        },
        "status": derive_status(delay_sec, magnitude, icon_category),
    }


async def fetch_incidents(
    client: httpx.AsyncClient,
    bbox: str,
    time_validity_filter: str,
) -> list[dict[str, Any]]:
    params = {
        "key": TOMTOM_API_KEY,
        "bbox": bbox,
        "fields": INCIDENT_FIELDS,
        "language": "pl-PL",
        "timeValidityFilter": time_validity_filter,
    }
    try:
        response = await client.get(TOMTOM_INCIDENTS_URL, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
        return payload.get("incidents") or []
    except httpx.HTTPStatusError as exc:
        logger.warning("TomTom incidents HTTP %s for bbox %s", exc.response.status_code, bbox)
    except Exception as exc:
        logger.warning("TomTom incidents fetch failed for bbox %s: %s", bbox, exc)
    return []


async def collect_tomtom_events() -> list[dict[str, Any]]:
    """Fetch present incidents from all configured port regions."""
    async with httpx.AsyncClient() as client:
        present_trojmiasto, present_szczecin, present_swinoujscie = await asyncio.gather(
            fetch_incidents(client, BBOX_TROJMIASTO, "present"),
            fetch_incidents(client, BBOX_SZCZECIN, "present"),
            fetch_incidents(client, BBOX_SWINOUJSCIE, "present"),
        )

    unified: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for incident in present_trojmiasto + present_szczecin + present_swinoujscie:
        event = incident_to_event(incident, "present")
        if event is None or event["event_id"] in seen_ids:
            continue
        seen_ids.add(event["event_id"])
        unified.append(event)

    logger.info("TomTom primary: %s present incidents", len(unified))
    return unified


def incident_heat_intensity(event: dict[str, Any]) -> float:
    """Map TomTom delay + magnitude to 0.15–1.0 heat weight."""
    metrics = event.get("metrics") or {}
    delay = int(metrics.get("delay_sec") or 0)
    magnitude = int(metrics.get("magnitude") or 0)
    status = event.get("status") or ""

    delay_factor = min(1.0, delay / 600.0)
    magnitude_factor = min(1.0, magnitude / 4.0)
    intensity = 0.55 * delay_factor + 0.35 * magnitude_factor
    if status == "CRITICAL":
        intensity = min(1.0, intensity + 0.15)
    return max(0.15, round(intensity, 3))


def _sample_line_heatmap_points(
    coordinates: list[list[float]],
    intensity: float,
    step: int = 2,
) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for index in range(0, len(coordinates), step):
        lon, lat = coordinates[index]
        points.append({"lat": float(lat), "lon": float(lon), "intensity": intensity})
    return points


def build_heatmap_points(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Convert TomTom incidents into weighted lat/lon points for a live heatmap layer.
    Line incidents are sampled along geometry; point incidents use centroid.
    """
    points: list[dict[str, Any]] = []
    seen: set[tuple[float, float]] = set()

    for event in events:
        if event.get("source_type") != "tomtom_traffic":
            continue

        intensity = incident_heat_intensity(event)
        geometry = event.get("geometry") or {}

        if geometry.get("type") == "LineString":
            coords = geometry.get("coordinates") or []
            for point in _sample_line_heatmap_points(coords, intensity):
                key = (round(point["lat"], 4), round(point["lon"], 4))
                if key in seen:
                    continue
                seen.add(key)
                points.append(point)
            continue

        location = event.get("location") or {}
        lat = location.get("lat")
        lon = location.get("lon")
        if lat is None or lon is None:
            continue
        key = (round(float(lat), 4), round(float(lon), 4))
        if key in seen:
            continue
        seen.add(key)
        points.append({"lat": float(lat), "lon": float(lon), "intensity": intensity})

    return points
