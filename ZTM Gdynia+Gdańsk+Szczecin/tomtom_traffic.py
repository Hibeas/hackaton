"""TomTom Traffic Incident Details — async fetch and normalization."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

TOMTOM_INCIDENTS_URL = "https://api.tomtom.com/traffic/services/5/incidentDetails"
TOMTOM_REQUEST_TIMEOUT = 30.0

BBOX_TROJMIASTO = "18.40,54.30,18.75,54.60"
BBOX_SZCZECIN = "14.45,53.30,14.90,53.55"
BBOX_SWINOUJSCIE = "14.15,53.85,14.45,54.02"

TOMTOM_REGIONS: tuple[tuple[str, str], ...] = (
    ("trojmiasto", BBOX_TROJMIASTO),
    ("szczecin", BBOX_SZCZECIN),
    ("swinoujscie", BBOX_SWINOUJSCIE),
)

INCIDENT_FIELDS = (
    "{incidents{type,geometry{type,coordinates},properties{"
    "id,iconCategory,magnitudeOfDelay,events{description,code,iconCategory},"
    "startTime,endTime,from,to,length,delay,roadNumbers,timeValidity,"
    "probabilityOfOccurrence,numberOfReports,lastReportTime}}}"
)

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

MAGNITUDE_PL: dict[int, str] = {
    0: "nieznana",
    1: "niska",
    2: "umiarkowana",
    3: "duża",
    4: "bardzo duża (np. zamknięcie drogi)",
}

PORT_CORRIDOR_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"sucharsk",
        r"marynarki",
        r"kwiatkowsk",
        r"\bS6\b",
        r"\b468\b",
        r"estakad",
        r"portow",
        r"obwodnic",
        r"tunel",
        r"swina",
        r"wyspy",
        r"slazacza",
        r"wojska",
        r"\bS3\b",
        r"dk93",
    )
)


def get_tomtom_api_key() -> str | None:
    key = os.environ.get("TOMTOM_API_KEY", "").strip()
    return key or None


def incident_status(delay_sec: int, magnitude: int, icon_category: int) -> str:
    if icon_category in (1, 8) or magnitude >= 3 or delay_sec >= 120:
        return "CRITICAL"
    if delay_sec >= 45 or magnitude >= 2 or icon_category == 6:
        return "CONGESTION"
    return "CLEAR"


def incident_centroid(incident: dict[str, Any]) -> tuple[float, float] | None:
    geometry = incident.get("geometry") or {}
    geom_type = geometry.get("type")
    coords = geometry.get("coordinates")
    if not coords:
        return None
    if geom_type == "Point":
        lon, lat = coords
        return float(lat), float(lon)
    if geom_type == "LineString":
        mid = coords[len(coords) // 2]
        return float(mid[1]), float(mid[0])
    return None


def infer_city(lat: float, lon: float, region: str) -> str:
    if region == "swinoujscie":
        return "Swinoujscie"
    if region == "szczecin":
        if lat > 53.88 and lon < 14.35:
            return "Swinoujscie"
        return "Szczecin"
    if lat > 54.45:
        return "Gdynia"
    if lon > 18.55:
        return "Gdansk"
    return "Trojmiasto"


def normalize_incident_geometry(incident: dict[str, Any]) -> dict[str, Any] | None:
    geometry = incident.get("geometry") or {}
    geom_type = geometry.get("type")
    raw_coords = geometry.get("coordinates")
    if not raw_coords:
        return None
    if geom_type == "Point":
        lon, lat = raw_coords
        return {"type": "Point", "coordinates": [float(lon), float(lat)]}
    if geom_type == "LineString":
        coordinates: list[list[float]] = []
        for point in raw_coords:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                continue
            coordinates.append([float(point[0]), float(point[1])])
        if len(coordinates) < 2:
            return None
        return {"type": "LineString", "coordinates": coordinates}
    return None


def road_label(props: dict[str, Any]) -> str:
    road_numbers = props.get("roadNumbers") or []
    if road_numbers:
        return ", ".join(str(r) for r in road_numbers)
    road_from = props.get("from") or "?"
    road_to = props.get("to") or "?"
    return f"{road_from} → {road_to}"


def corridor_priority(road_name: str, road_numbers: list[str]) -> str:
    haystack = f"{road_name} {' '.join(road_numbers)}"
    for pattern in PORT_CORRIDOR_PATTERNS:
        if pattern.search(haystack):
            return "high"
    return "normal"


def format_delay_minutes(delay_sec: int) -> str:
    minutes = max(1, round(delay_sec / 60))
    return f"~{minutes} min"


def to_iso_timestamp(raw: str | None) -> str:
    if not raw:
        return datetime.now(timezone.utc).isoformat()
    normalized = raw.strip().replace("Z", "+00:00")
    if " " in normalized and "T" not in normalized:
        normalized = normalized.replace(" ", "T", 1)
    try:
        return datetime.fromisoformat(normalized).isoformat()
    except ValueError:
        return datetime.now(timezone.utc).isoformat()


def build_driver_summary_pl(
    *,
    primary_reason: str,
    category_pl: str,
    roads: str,
    delay_sec: int,
    length_m: int,
    magnitude_label: str,
    time_validity: str,
    start_time: str | None,
    end_time: str | None,
    probability: str | None,
) -> str:
    when = "teraz" if time_validity == "present" else "planowane"
    parts = [
        f"{primary_reason} ({category_pl}) na {roads}.",
        f"Opóźnienie {format_delay_minutes(delay_sec)}, długość {length_m} m, intensywność: {magnitude_label}.",
        f"Status: {when}",
    ]
    if start_time:
        parts.append(f"od {start_time}")
    if end_time:
        parts.append(f"do {end_time}")
    if probability:
        parts.append(f"pewność: {probability}")
    return " ".join(parts) + "."


def build_tomtom_event(
    incident: dict[str, Any],
    *,
    region: str,
    time_validity: str,
) -> dict[str, Any] | None:
    props = incident.get("properties") or {}
    raw_id = props.get("id")
    if raw_id is None:
        return None

    centroid = incident_centroid(incident)
    if centroid is None:
        return None
    lat, lon = centroid

    icon_category = int(props.get("iconCategory") or 0)
    magnitude = int(props.get("magnitudeOfDelay") or 0)
    delay_sec = int(props.get("delay") or 0)
    length_m = int(props.get("length") or 0)
    category_pl = ICON_CATEGORY_PL.get(icon_category, f"kategoria {icon_category}")
    magnitude_label = MAGNITUDE_PL.get(magnitude, "?")

    events = props.get("events") or []
    descriptions = [e.get("description", "").strip() for e in events if e.get("description")]
    primary_reason = descriptions[0] if descriptions else category_pl

    roads = road_label(props)
    road_numbers = [str(r) for r in (props.get("roadNumbers") or [])]
    start_time = props.get("startTime")
    end_time = props.get("endTime")
    probability = props.get("probabilityOfOccurrence")
    validity = props.get("timeValidity") or time_validity

    entity_id = str(raw_id)
    event_id = f"tomtom_{region}_{entity_id}_{validity}"

    return {
        "event_id": event_id,
        "record_kind": "traffic_incident",
        "entity_id": entity_id,
        "city": infer_city(lat, lon, region),
        "source_type": "tomtom_traffic",
        "timestamp": to_iso_timestamp(start_time),
        "location": {
            "lat": lat,
            "lon": lon,
            "road_name": roads,
        },
        "geometry": normalize_incident_geometry(incident),
        "metrics": {
            "speed_kmh": None,
            "intensity_vph": None,
            "delay_sec": delay_sec,
            "length_m": length_m,
            "magnitude": magnitude,
            "icon_category": icon_category,
            "number_of_reports": props.get("numberOfReports"),
        },
        "context": {
            "region": region,
            "time_validity": validity,
            "category_pl": category_pl,
            "primary_reason": primary_reason,
            "event_descriptions": descriptions,
            "from": props.get("from"),
            "to": props.get("to"),
            "road_numbers": road_numbers,
            "start_time": start_time,
            "end_time": end_time,
            "last_report_time": props.get("lastReportTime"),
            "probability": probability,
            "geometry_type": (incident.get("geometry") or {}).get("type"),
            "corridor_priority": corridor_priority(roads, road_numbers),
            "driver_summary_pl": build_driver_summary_pl(
                primary_reason=primary_reason,
                category_pl=category_pl,
                roads=roads,
                delay_sec=delay_sec,
                length_m=length_m,
                magnitude_label=magnitude_label,
                time_validity=validity,
                start_time=start_time,
                end_time=end_time,
                probability=probability,
            ),
        },
        "status": incident_status(delay_sec, magnitude, icon_category),
    }


def build_tomtom_events(
    payload: dict[str, Any] | None,
    *,
    region: str,
    time_validity: str,
) -> list[dict[str, Any]]:
    if not payload:
        return []
    incidents = payload.get("incidents") or []
    events: list[dict[str, Any]] = []
    for incident in incidents:
        if not isinstance(incident, dict):
            continue
        event = build_tomtom_event(incident, region=region, time_validity=time_validity)
        if event is not None:
            events.append(event)
    return events


async def fetch_traffic_incidents(
    client: httpx.AsyncClient,
    api_key: str,
    bbox: str,
    time_validity_filter: str = "present",
) -> dict[str, Any] | None:
    params = {
        "key": api_key,
        "bbox": bbox,
        "fields": INCIDENT_FIELDS,
        "language": "pl-PL",
        "timeValidityFilter": time_validity_filter,
    }
    try:
        response = await client.get(
            TOMTOM_INCIDENTS_URL,
            params=params,
            timeout=TOMTOM_REQUEST_TIMEOUT,
        )
        if response.status_code != 200:
            logger.warning(
                "TomTom incidents HTTP %s for bbox=%s validity=%s",
                response.status_code,
                bbox,
                time_validity_filter,
            )
            return None
        return response.json()
    except httpx.HTTPError as exc:
        logger.warning("TomTom incidents request failed: %s", exc)
        return None


async def collect_tomtom_events(
    client: httpx.AsyncClient,
    api_key: str,
) -> list[dict[str, Any]]:
    tasks = []
    meta: list[tuple[str, str]] = []
    for region, bbox in TOMTOM_REGIONS:
        for validity in ("present", "future"):
            tasks.append(fetch_traffic_incidents(client, api_key, bbox, validity))
            meta.append((region, validity))

    results = await asyncio.gather(*tasks)
    events: list[dict[str, Any]] = []
    for (region, validity), payload in zip(meta, results):
        events.extend(build_tomtom_events(payload, region=region, time_validity=validity))
    return events
