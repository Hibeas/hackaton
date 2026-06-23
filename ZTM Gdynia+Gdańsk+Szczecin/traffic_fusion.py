"""Fuse TomTom incidents with municipal ZTM data (Gdynia loops + bus GPS)."""

from __future__ import annotations

import math
from typing import Any

FUSION_RADIUS_KM = 0.5
PORT_CORRELATION_RADIUS_KM = 5.0
SLOW_BUS_SPEED_KMH = 12.0


def distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = a
    lat2, lon2 = b
    dlat = (lat2 - lat1) * 111.0
    dlon = (lon2 - lon1) * 111.0 * 0.65
    return math.sqrt(dlat ** 2 + dlon ** 2)


def event_point(event: dict[str, Any]) -> tuple[float, float] | None:
    location = event.get("location") or {}
    lat = location.get("lat")
    lon = location.get("lon")
    if lat is None or lon is None:
        return None
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (TypeError, ValueError):
        return None
    if lat_f == 0 and lon_f == 0:
        return None
    return lat_f, lon_f


def geometry_sample_points(geometry: dict[str, Any] | None) -> list[tuple[float, float]]:
    if not geometry:
        return []
    coords = geometry.get("coordinates") or []
    geom_type = geometry.get("type")
    if geom_type == "Point" and len(coords) >= 2:
        return [(float(coords[1]), float(coords[0]))]
    if geom_type == "LineString":
        points: list[tuple[float, float]] = []
        step = max(1, len(coords) // 8)
        for point in coords[::step]:
            if isinstance(point, (list, tuple)) and len(point) >= 2:
                points.append((float(point[1]), float(point[0])))
        return points
    return []


def min_distance_to_event(target: dict[str, Any], reference: dict[str, Any]) -> float | None:
    ref_points = geometry_sample_points(reference.get("geometry"))
    ref_point = event_point(reference)
    if ref_point:
        ref_points.append(ref_point)
    if not ref_points:
        return None

    tgt_points = geometry_sample_points(target.get("geometry"))
    tgt_point = event_point(target)
    if tgt_point:
        tgt_points.append(tgt_point)
    if not tgt_points:
        return None

    return min(distance_km(tp, rp) for tp in tgt_points for rp in ref_points)


def nearby_gdynia_segments(
    incident: dict[str, Any],
    segments: list[dict[str, Any]],
    *,
    radius_km: float = FUSION_RADIUS_KM,
) -> list[dict[str, Any]]:
    matches: list[tuple[float, dict[str, Any]]] = []
    for segment in segments:
        dist = min_distance_to_event(incident, segment)
        if dist is not None and dist <= radius_km:
            matches.append((dist, segment))
    matches.sort(key=lambda item: item[0])
    return [segment for _, segment in matches]


def nearby_transit_probes(
    incident: dict[str, Any],
    vehicles: list[dict[str, Any]],
    *,
    radius_km: float = FUSION_RADIUS_KM,
    slow_speed: float = SLOW_BUS_SPEED_KMH,
) -> dict[str, Any]:
    slow_buses: list[dict[str, Any]] = []
    all_nearby = 0
    speeds: list[float] = []

    for vehicle in vehicles:
        dist = min_distance_to_event(incident, vehicle)
        if dist is None or dist > radius_km:
            continue
        all_nearby += 1
        speed = float((vehicle.get("metrics") or {}).get("speed_kmh") or 0)
        speeds.append(speed)
        if speed < slow_speed:
            slow_buses.append(
                {
                    "vehicle_id": vehicle.get("entity_id"),
                    "city": vehicle.get("city"),
                    "speed_kmh": speed,
                    "distance_km": round(dist, 3),
                }
            )

    avg_speed = round(sum(speeds) / len(speeds), 1) if speeds else None
    return {
        "slow_bus_count": len(slow_buses),
        "nearby_bus_count": all_nearby,
        "avg_speed_kmh": avg_speed,
        "slow_buses": slow_buses[:8],
    }


def compute_confidence(
    incident: dict[str, Any],
    gdynia_matches: list[dict[str, Any]],
    transit: dict[str, Any],
) -> str:
    gdynia_critical = any(seg.get("status") == "CRITICAL" for seg in gdynia_matches)
    gdynia_congested = any(seg.get("status") in ("CRITICAL", "CONGESTION") for seg in gdynia_matches)
    slow_count = int(transit.get("slow_bus_count") or 0)

    if gdynia_critical or slow_count >= 3:
        return "high"
    if gdynia_congested or slow_count >= 1:
        return "medium"
    if incident.get("status") in ("CRITICAL", "CONGESTION"):
        return "medium"
    return "low"


def segment_summary(segment: dict[str, Any], trend_pct: float | None = None) -> dict[str, Any]:
    metrics = segment.get("metrics") or {}
    item: dict[str, Any] = {
        "segment_id": segment.get("entity_id"),
        "event_id": segment.get("event_id"),
        "intensity_vph": metrics.get("intensity_vph"),
        "speed_kmh": metrics.get("speed_kmh"),
        "status": segment.get("status"),
    }
    if trend_pct is not None:
        item["trend_pct_15min"] = round(trend_pct, 1)
    return item


def build_fused_summary_pl(
    base_summary: str,
    *,
    confidence: str,
    gdynia_matches: list[dict[str, Any]],
    transit: dict[str, Any],
    segment_trends: dict[str, float],
) -> str:
    parts = [base_summary.rstrip(".")]

    if gdynia_matches:
        seg = gdynia_matches[0]
        metrics = seg.get("metrics") or {}
        seg_id = seg.get("entity_id")
        trend = segment_trends.get(str(seg_id)) if seg_id else None
        trend_text = f", trend +{trend:.0f}% vs 15 min" if trend and trend > 5 else ""
        parts.append(
            f"Potwierdzone: segment Gdynia #{seg_id} — "
            f"{metrics.get('intensity_vph')} poj./h{trend_text}"
        )

    slow_count = int(transit.get("slow_bus_count") or 0)
    if slow_count > 0:
        avg = transit.get("avg_speed_kmh")
        parts.append(f"{slow_count} autobusów <12 km/h w okolicy (śr. {avg} km/h)")

    confidence_pl = {"high": "wysoka", "medium": "średnia", "low": "niska"}.get(confidence, confidence)
    parts.append(f"Pewność: {confidence_pl}")
    return ". ".join(parts) + "."


def enrich_tomtom_with_ztm(
    incident: dict[str, Any],
    gdynia_segments: list[dict[str, Any]],
    transit_vehicles: list[dict[str, Any]],
    segment_trends: dict[str, float],
) -> dict[str, Any]:
    enriched = dict(incident)
    context = dict(enriched.get("context") or {})

    matches = nearby_gdynia_segments(incident, gdynia_segments)
    transit = nearby_transit_probes(incident, transit_vehicles)
    confidence = compute_confidence(incident, matches, transit)

    gdynia_summaries = []
    for seg in matches[:5]:
        seg_id = str(seg.get("entity_id"))
        gdynia_summaries.append(segment_summary(seg, segment_trends.get(seg_id)))

    corroboration = {
        "confidence": confidence,
        "gdynia_segments": gdynia_summaries,
        "transit_probes": {
            "slow_bus_count": transit["slow_bus_count"],
            "nearby_bus_count": transit["nearby_bus_count"],
            "avg_speed_kmh": transit["avg_speed_kmh"],
        },
    }
    context["corroboration"] = corroboration
    context["driver_summary_pl"] = build_fused_summary_pl(
        context.get("driver_summary_pl") or "",
        confidence=confidence,
        gdynia_matches=matches,
        transit=transit,
        segment_trends=segment_trends,
    )
    enriched["context"] = context
    return enriched


def mark_gdynia_corroboration(
    segment: dict[str, Any],
    nearby_incidents: list[dict[str, Any]],
) -> dict[str, Any]:
    enriched = dict(segment)
    if not nearby_incidents:
        if segment.get("status") in ("CRITICAL", "CONGESTION"):
            enriched["context"] = {
                "corroboration": {
                    "confidence": "medium",
                    "tomtom_incident_nearby": False,
                    "note": "Kongestia widoczna na pętlach — brak incydentu TomTom w pobliżu",
                    "flag": "tomtom_gap",
                }
            }
        return enriched

    incident = nearby_incidents[0]
    inc_context = incident.get("context") or {}
    enriched["context"] = {
        "corroboration": {
            "confidence": (inc_context.get("corroboration") or {}).get("confidence", "medium"),
            "tomtom_incident_nearby": True,
            "tomtom_event_id": incident.get("event_id"),
            "tomtom_cause": inc_context.get("primary_reason"),
            "tomtom_road": (incident.get("location") or {}).get("road_name"),
        }
    }
    return enriched


def mark_transit_corroboration(
    vehicle: dict[str, Any],
    nearby_incidents: list[dict[str, Any]],
) -> dict[str, Any]:
    enriched = dict(vehicle)
    speed = float((vehicle.get("metrics") or {}).get("speed_kmh") or 0)
    if speed >= SLOW_BUS_SPEED_KMH and not nearby_incidents:
        return enriched

    if nearby_incidents:
        incident = nearby_incidents[0]
        inc_context = incident.get("context") or {}
        enriched["context"] = {
            "corroboration": {
                "near_tomtom_incident": True,
                "tomtom_cause": inc_context.get("primary_reason"),
                "tomtom_road": (incident.get("location") or {}).get("road_name"),
            }
        }
    elif speed < SLOW_BUS_SPEED_KMH:
        enriched["context"] = {
            "corroboration": {
                "near_tomtom_incident": False,
                "flag": "transit_slow_no_tomtom",
                "note": "Spowolnienie autobusu bez incydentu TomTom w pobliżu",
            }
        }
    return enriched


def incidents_near_event(
    event: dict[str, Any],
    incidents: list[dict[str, Any]],
    *,
    radius_km: float = FUSION_RADIUS_KM,
) -> list[dict[str, Any]]:
    matches: list[tuple[float, dict[str, Any]]] = []
    for incident in incidents:
        if (incident.get("context") or {}).get("time_validity") != "present":
            continue
        dist = min_distance_to_event(event, incident)
        if dist is not None and dist <= radius_km:
            matches.append((dist, incident))
    matches.sort(key=lambda item: item[0])
    return [inc for _, inc in matches]


def fuse_traffic_events(
    ztm_events: list[dict[str, Any]],
    tomtom_events: list[dict[str, Any]],
    segment_trends: dict[str, float] | None = None,
    port_events: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Merge ZTM + TomTom into one event list with cross-source corroboration."""
    trends = segment_trends or {}
    gdynia_segments = [e for e in ztm_events if e.get("record_kind") == "road_segment"]
    transit_vehicles = [e for e in ztm_events if e.get("record_kind") == "vehicle"]
    present_incidents = [
        e
        for e in tomtom_events
        if e.get("source_type") == "tomtom_traffic"
        and (e.get("context") or {}).get("time_validity") == "present"
    ]

    fused_tomtom = [
        enrich_tomtom_with_ztm(inc, gdynia_segments, transit_vehicles, trends)
        for inc in tomtom_events
        if inc.get("source_type") == "tomtom_traffic"
    ]

    fused_ztm: list[dict[str, Any]] = []
    for event in ztm_events:
        if event.get("record_kind") == "road_segment":
            nearby = incidents_near_event(event, present_incidents)
            fused_ztm.append(mark_gdynia_corroboration(event, nearby))
        elif event.get("record_kind") == "vehicle":
            nearby = incidents_near_event(event, present_incidents)
            fused_ztm.append(mark_transit_corroboration(event, nearby))
        else:
            fused_ztm.append(event)

    road_events = fused_ztm + fused_tomtom
    if port_events:
        return correlate_port_with_traffic(port_events, road_events)
    return road_events


def events_near_point(
    lat: float,
    lon: float,
    candidates: list[dict[str, Any]],
    *,
    radius_km: float = PORT_CORRELATION_RADIUS_KM,
) -> list[dict[str, Any]]:
    matches: list[tuple[float, dict[str, Any]]] = []
    for event in candidates:
        point = event_point(event)
        if point is None:
            continue
        dist = distance_km((lat, lon), point)
        if dist <= radius_km:
            matches.append((dist, event))
    matches.sort(key=lambda item: item[0])
    return [event for _, event in matches]


def build_port_context_pl(
    road_event: dict[str, Any],
    nearby_port: list[dict[str, Any]],
) -> str | None:
    if not nearby_port:
        return None
    location = road_event.get("location") or {}
    road = location.get("road_name") or road_event.get("entity_id") or "droga dojazdowa"
    calls = [e for e in nearby_port if e.get("record_kind") == "port_call"]
    activities = [e for e in nearby_port if e.get("record_kind") == "container_activity"]
    parts: list[str] = []

    if activities:
        top = max(
            activities,
            key=lambda item: (item.get("metrics") or {}).get("moves_last_hour", 0),
        )
        ops = (top.get("context") or {}).get("port_ops") or {}
        terminal = ops.get("terminal") or (top.get("location") or {}).get("road_name")
        moves = (top.get("metrics") or {}).get("moves_last_hour", 0)
        parts.append(f"{moves} ruchów kontenerów/h przy {terminal}")

    expected = [
        e
        for e in calls
        if (e.get("context") or {}).get("port_ops", {}).get("call_status") == "expected"
    ]
    in_port = [
        e
        for e in calls
        if (e.get("context") or {}).get("port_ops", {}).get("call_status") == "in_port"
    ]
    if expected:
        names = [
            (e.get("metrics") or {}).get("ship_name") or "statek"
            for e in expected[:3]
        ]
        parts.append(f"{len(expected)} nadchodzących zawinięć ({', '.join(names)})")
    if in_port:
        parts.append(f"{len(in_port)} statków przy nabrzeżu")

    if not parts:
        return None
    return f"Kontekst portowy przy {road}: " + "; ".join(parts) + "."


def correlate_port_with_traffic(
    port_events: list[dict[str, Any]],
    road_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    enriched_road: list[dict[str, Any]] = []
    for event in road_events:
        if event.get("record_kind") in ("port_call", "container_activity"):
            enriched_road.append(event)
            continue
        if event.get("status") not in ("CRITICAL", "CONGESTION"):
            enriched_road.append(event)
            continue

        point = event_point(event)
        if point is None:
            enriched_road.append(event)
            continue

        nearby_port = events_near_point(point[0], point[1], port_events)
        if not nearby_port:
            enriched_road.append(event)
            continue

        updated = dict(event)
        context = dict(updated.get("context") or {})
        port_context_pl = build_port_context_pl(event, nearby_port)
        if port_context_pl:
            context["port_context_pl"] = port_context_pl
            context["port_correlation"] = {
                "nearby_port_events": len(nearby_port),
                "terminals": list(
                    dict.fromkeys(
                        (e.get("context") or {}).get("port_ops", {}).get("terminal")
                        for e in nearby_port
                        if (e.get("context") or {}).get("port_ops", {}).get("terminal")
                    )
                )[:5],
            }
            hint = next(
                (
                    (e.get("context") or {}).get("port_ops", {}).get("truck_demand_hint")
                    for e in nearby_port
                    if (e.get("context") or {}).get("port_ops", {}).get("truck_demand_hint") == "high"
                ),
                None,
            )
            if hint == "high" and event.get("source_type") == "tomtom_traffic":
                context["driver_summary_pl"] = (
                    (context.get("driver_summary_pl") or "").rstrip(".")
                    + ". Wysoki ruch kontenerowy w porcie — rozważ opóźnienie slotów bram i trasy alternatywne."
                )
        updated["context"] = context
        enriched_road.append(updated)

    port_only = [e for e in port_events if e.get("record_kind") in ("port_call", "container_activity")]
    road_only = [e for e in enriched_road if e.get("record_kind") not in ("port_call", "container_activity")]
    return road_only + port_only
