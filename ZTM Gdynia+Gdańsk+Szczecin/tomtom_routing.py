"""TomTom Routing API — optional route forecast and bypass (from TomTom/mainv2.py)."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from tomtom_traffic import get_tomtom_api_key

logger = logging.getLogger(__name__)

TOMTOM_ROUTING_URL = "https://api.tomtom.com/routing/1/calculateRoute/{locations}/json"
REQUEST_TIMEOUT = 30.0

ROUTE_ORIGIN = "54.3520,18.6466"
ROUTE_DESTINATION = "54.5189,18.5305"
PREDICTION_HOURS = (3, 4)


def routing_enabled() -> bool:
    return os.environ.get("TOMTOM_ROUTING_ENABLED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _poland_timezone():
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo("Europe/Warsaw")
    except Exception:
        return timezone.utc


def depart_at_iso(hours_from_now: int = 0) -> str:
    tz = _poland_timezone()
    target = datetime.now(tz=tz) + timedelta(hours=hours_from_now)
    return target.strftime("%Y-%m-%dT%H:%M:%S")


def format_duration(seconds: int) -> str:
    minutes = max(1, int(round(seconds / 60)))
    return f"{minutes} min"


async def calculate_route_locations(
    client: httpx.AsyncClient,
    api_key: str,
    locations: str,
    *,
    depart_at: str = "now",
    max_alternatives: int = 0,
) -> dict[str, Any] | None:
    params: dict[str, Any] = {
        "key": api_key,
        "traffic": "true",
        "travelMode": "car",
        "routeType": "fastest",
        "sectionType": "traffic",
        "computeTravelTimeFor": "all",
        "language": "pl-PL",
        "maxAlternatives": max_alternatives,
    }
    if depart_at != "now":
        params["departAt"] = depart_at
    url = TOMTOM_ROUTING_URL.format(locations=locations)
    try:
        response = await client.get(url, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        logger.warning("TomTom routing failed: %s", exc)
        return None


def _summarize_route(route: dict[str, Any]) -> dict[str, Any]:
    summary = route.get("summary") or {}
    travel_time = int(summary.get("travelTimeInSeconds") or 0)
    delay = int(summary.get("trafficDelayInSeconds") or 0)
    length_m = int(summary.get("lengthInMeters") or 0)
    points: list[list[float]] = []
    for leg in route.get("legs") or []:
        for point in leg.get("points") or []:
            points.append([float(point["latitude"]), float(point["longitude"])])
    return {
        "travel_time_sec": travel_time,
        "travel_time_label": format_duration(travel_time),
        "traffic_delay_sec": delay,
        "traffic_delay_label": format_duration(delay) if delay else "0 min",
        "length_m": length_m,
        "geometry": {"type": "LineString", "coordinates": [[p[1], p[0]] for p in points]} if points else None,
    }


async def build_route_forecast(
    *,
    origin: str = ROUTE_ORIGIN,
    destination: str = ROUTE_DESTINATION,
) -> dict[str, Any]:
    api_key = get_tomtom_api_key()
    if not api_key:
        return {"enabled": False, "error": "TOMTOM_API_KEY not set"}
    if not routing_enabled():
        return {"enabled": False, "error": "TOMTOM_ROUTING_ENABLED is false"}

    locations = f"{origin}:{destination}"
    async with httpx.AsyncClient() as client:
        now_payload = await calculate_route_locations(client, api_key, locations, depart_at="now")
        forecasts: list[dict[str, Any]] = []
        for hours in PREDICTION_HOURS:
            payload = await calculate_route_locations(
                client,
                api_key,
                locations,
                depart_at=depart_at_iso(hours),
            )
            route = ((payload or {}).get("routes") or [None])[0]
            if route:
                item = _summarize_route(route)
                item["depart_in_hours"] = hours
                forecasts.append(item)

    routes = (now_payload or {}).get("routes") or []
    main_route = _summarize_route(routes[0]) if routes else None
    return {
        "enabled": True,
        "origin": origin,
        "destination": destination,
        "main_route_now": main_route,
        "forecasts": forecasts,
    }


async def compute_bypass(
    *,
    lat: float,
    lon: float,
    origin: str = ROUTE_ORIGIN,
    destination: str = ROUTE_DESTINATION,
) -> dict[str, Any]:
    """Lazy bypass around a point (simplified from TomTom/mainv2.py)."""
    api_key = get_tomtom_api_key()
    if not api_key:
        return {"enabled": False, "recommended": False, "error": "TOMTOM_API_KEY not set"}
    if not routing_enabled():
        return {"enabled": False, "recommended": False, "error": "TOMTOM_ROUTING_ENABLED is false"}

    detour_dirs = [
        ("północ", 0.012, 0.015),
        ("południe", -0.012, -0.015),
        ("wschód", 0.015, 0.012),
        ("zachód", -0.015, -0.012),
    ]
    candidates: list[dict[str, Any]] = []
    async with httpx.AsyncClient() as client:
        direct_payload = await calculate_route_locations(
            client, api_key, f"{origin}:{destination}", max_alternatives=0
        )
        direct_routes = (direct_payload or {}).get("routes") or []
        direct_time = int((direct_routes[0].get("summary") or {}).get("travelTimeInSeconds") or 0) if direct_routes else 0

        for side, dlat, dlon in detour_dirs:
            waypoint = f"{lat + dlat:.5f},{lon + dlon:.5f}"
            payload = await calculate_route_locations(
                client,
                api_key,
                f"{origin}:{waypoint}:{destination}",
                max_alternatives=0,
            )
            routes = (payload or {}).get("routes") or []
            if not routes:
                continue
            summary = _summarize_route(routes[0])
            travel = int(summary.get("travel_time_sec") or 0)
            saved = direct_time - travel if direct_time else 0
            candidates.append(
                {
                    "via": f"od strony {side}",
                    "scope": "trip",
                    "saved_sec": saved,
                    **summary,
                }
            )

    if not candidates:
        return {"enabled": True, "recommended": False}

    best = min(candidates, key=lambda item: (item.get("traffic_delay_sec") or 0, item.get("travel_time_sec") or 0))
    best["recommended"] = True
    best["enabled"] = True
    return best
