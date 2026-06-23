"""Anomaly detection, trend prediction, and operational reports."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

from traffic_history import EntityHistory, TrafficHistory, SAMPLE_INTERVAL_SECONDS

KEY_ROAD_PATTERN = (
    "S6", "468", "sucharsk", "marynarki", "kwiatkowsk", "estakad",
    "tunel", "swina", "wyspy", "slazacza", "wojska", "S3", "dk93",
)


def parse_event_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    normalized = str(raw).strip().replace("Z", "+00:00")
    if " " in normalized and "T" not in normalized:
        normalized = normalized.replace(" ", "T", 1)
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def estimate_speed_from_intensity(intensity_vph: float) -> float:
    if intensity_vph <= 100:
        return 50.0
    if intensity_vph <= 400:
        return 40.0
    if intensity_vph <= 700:
        return 32.0
    if intensity_vph <= 1000:
        return 24.0
    if intensity_vph <= 1300:
        return 16.0
    return 8.0


def intensity_to_status(intensity_vph: float) -> str:
    speed = estimate_speed_from_intensity(intensity_vph)
    if speed < 12:
        return "CRITICAL"
    if speed < 25:
        return "CONGESTION"
    return "CLEAR"


def distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = a
    lat2, lon2 = b
    dlat = (lat2 - lat1) * 111.0
    dlon = (lon2 - lon1) * 111.0 * 0.65
    return math.sqrt(dlat ** 2 + dlon ** 2)


def is_key_corridor(text: str) -> bool:
    lower = text.lower()
    return any(token in lower for token in KEY_ROAD_PATTERN)


def linear_slope(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    xs = list(range(n))
    x_mean = sum(xs) / n
    y_mean = sum(values) / n
    num = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, values))
    den = sum((x - x_mean) ** 2 for x in xs)
    if den == 0:
        return 0.0
    return num / den


def recommend_for_event(event: dict[str, Any], *, growing: bool = False, minutes_ahead: int | None = None) -> str:
    context = event.get("context") or {}
    metrics = event.get("metrics") or {}
    location = event.get("location") or {}
    road = location.get("road_name") or event.get("entity_id") or "ten odcinek"
    icon_category = metrics.get("icon_category")
    time_validity = context.get("time_validity")
    source = event.get("source_type")
    corroboration = context.get("corroboration") or {}
    confidence = corroboration.get("confidence")

    if icon_category in (1, 8):
        rec = f"Unikaj {road}. Sprawdź alternatywne dojazdy na mapie incydentów."
        if confidence == "high":
            rec += " Dane miejskie potwierdzają zator."
        return rec
    if time_validity == "future":
        start = context.get("start_time") or "wkrótce"
        return f"Od {start} planowana przerwa na {road} — wyjedź wcześniej lub zmień trasę."
    if growing and minutes_ahead:
        return f"Korek narasta na {road} — rozważ opóźnienie wyjazdu o {minutes_ahead} min (sygnał z pętli Gdynia)."
    if corroboration.get("flag") == "tomtom_gap":
        return (
            f"Kongestja na {road} bez incydentu TomTom — reaguj na dane pętli indukcyjnych, "
            f"rozważ rozproszenie ruchu ciężarówek."
        )
    if source == "public_transit_gps":
        return f"Spowolnienie na korytarzu {road} (sygnał z GPS autobusów) — monitoruj sytuację."
    if confidence == "low":
        return f"Incydent TomTom na {road} bez potwierdzenia ZTM — zweryfikuj przed przekierowaniem ciężarówek."
    return f"Monitoruj sytuację na {road}; rozważ rozproszenie ruchu ciężarówek w czasie."


def detect_intensity_trend(entity: EntityHistory, window_minutes: int = 15) -> dict[str, Any] | None:
    window = timedelta(minutes=window_minutes)
    points = [
        p
        for p in entity.points_in_window(window)
        if p.intensity_vph is not None and p.record_kind == "road_segment"
    ]
    if len(points) < 6:
        return None

    intensities = [float(p.intensity_vph) for p in points]  # type: ignore[arg-type]
    slope = linear_slope(intensities)
    if slope <= 5:
        return None

    current = intensities[-1]
    avg_15 = sum(intensities) / len(intensities)
    if current < avg_15 * 1.5 or current < 700:
        return None

    projected = current + slope * (30 / SAMPLE_INTERVAL_SECONDS)
    if intensity_to_status(projected) != "CRITICAL":
        return None

    minutes_ahead = max(10, min(45, int(round((1300 - current) / max(slope, 1) * (SAMPLE_INTERVAL_SECONDS / 60)))))
    latest = entity.latest()
    return {
        "entity_id": entity.entity_id,
        "event_id": entity.event_id,
        "location": latest.road_name if latest else entity.entity_id,
        "city": latest.city if latest else None,
        "predicted_status": "CRITICAL",
        "predicted_in_minutes": minutes_ahead,
        "confidence": "medium",
        "method": "intensity_trend",
        "message_pl": (
            f"Natężenie rośnie na {latest.road_name if latest else entity.entity_id} "
            f"— szacowany korek za ~{minutes_ahead} min (pętle Gdynia)"
        ),
    }


def collect_segment_trends(history: TrafficHistory) -> dict[str, float]:
    trends: dict[str, float] = {}
    for entity in history.all_entities():
        if entity.latest() and entity.latest().record_kind == "road_segment":  # type: ignore[union-attr]
            trend = entity.intensity_trend_pct()
            if trend is not None:
                trends[entity.entity_id] = trend
    return trends


def detect_anomalies(
    events: list[dict[str, Any]],
    history: TrafficHistory,
    *,
    previous_tomtom_present: set[str] | None = None,
) -> list[dict[str, Any]]:
    anomalies: list[dict[str, Any]] = []
    prev_tomtom = previous_tomtom_present or set()

    for event in events:
        entity_id = history.entity_key(event)
        entity = history.get_entity(entity_id)
        metrics = event.get("metrics") or {}
        context = event.get("context") or {}
        location = event.get("location") or {}

        if event.get("record_kind") == "road_segment" and entity:
            corroboration = context.get("corroboration") or {}
            if corroboration.get("flag") == "tomtom_gap" and event.get("status") in ("CRITICAL", "CONGESTION"):
                anomalies.append(
                    {
                        "anomaly_type": "tomtom_gap",
                        "entity_id": entity_id,
                        "event_id": event.get("event_id"),
                        "city": event.get("city"),
                        "location": location.get("road_name"),
                        "message_pl": (
                            f"Kongestja na segmencie {event.get('entity_id')} bez incydentu TomTom w pobliżu "
                            f"({metrics.get('intensity_vph')} poj./h)"
                        ),
                        "severity": event.get("status"),
                    }
                )
            window = timedelta(minutes=15)
            window_points = [
                p for p in entity.points_in_window(window) if p.intensity_vph is not None
            ]
            if len(window_points) >= 4:
                current = float(metrics.get("intensity_vph") or 0)
                avg = sum(float(p.intensity_vph) for p in window_points[:-1]) / max(1, len(window_points) - 1)
                if current > avg * 1.5 and current > 700:
                    anomalies.append(
                        {
                            "anomaly_type": "intensity_spike",
                            "entity_id": entity_id,
                            "event_id": event.get("event_id"),
                            "city": event.get("city"),
                            "location": location.get("road_name"),
                            "message_pl": f"Skok natężenia na {location.get('road_name')} ({int(current)} poj./h)",
                            "severity": event.get("status"),
                        }
                    )

        if event.get("source_type") == "tomtom_traffic" and context.get("time_validity") == "present":
            if event.get("status") == "CRITICAL" and entity_id not in prev_tomtom:
                anomalies.append(
                    {
                        "anomaly_type": "new_incident",
                        "entity_id": entity_id,
                        "event_id": event.get("event_id"),
                        "city": event.get("city"),
                        "location": location.get("road_name"),
                        "message_pl": context.get("driver_summary_pl")
                        or f"Nowy incydent: {location.get('road_name')}",
                        "severity": "CRITICAL",
                    }
                )
            corroboration = context.get("corroboration") or {}
            if corroboration.get("confidence") == "low" and event.get("status") in ("CRITICAL", "CONGESTION"):
                anomalies.append(
                    {
                        "anomaly_type": "unverified_tomtom",
                        "entity_id": entity_id,
                        "event_id": event.get("event_id"),
                        "city": event.get("city"),
                        "location": location.get("road_name"),
                        "message_pl": f"Incydent TomTom bez potwierdzenia ZTM: {location.get('road_name')}",
                        "severity": event.get("status"),
                    }
                )
            if entity:
                window = timedelta(minutes=15)
                delay_points = [p for p in entity.points_in_window(window) if p.delay_sec is not None]
                if len(delay_points) >= 2:
                    prev_delay = delay_points[-2].delay_sec or 0
                    curr_delay = delay_points[-1].delay_sec or 0
                    if curr_delay - prev_delay > 60:
                        anomalies.append(
                            {
                                "anomaly_type": "delay_escalation",
                                "entity_id": entity_id,
                                "event_id": event.get("event_id"),
                                "city": event.get("city"),
                                "location": location.get("road_name"),
                                "message_pl": (
                                    f"Opóźnienie rośnie na {location.get('road_name')}: "
                                    f"+{curr_delay - prev_delay} s"
                                ),
                                "severity": event.get("status"),
                            }
                        )

        if context.get("time_validity") == "future":
            start = parse_event_datetime(context.get("start_time"))
            road_text = str(location.get("road_name") or "")
            if start and is_key_corridor(road_text):
                minutes_until = (start - datetime.now(timezone.utc)).total_seconds() / 60.0
                if 0 < minutes_until <= 120:
                    anomalies.append(
                        {
                            "anomaly_type": "predicted_disruption",
                            "entity_id": entity_id,
                            "event_id": event.get("event_id"),
                            "city": event.get("city"),
                            "location": location.get("road_name"),
                            "message_pl": context.get("driver_summary_pl")
                            or f"Planowane zdarzenie na {road_text}",
                            "severity": "CONGESTION",
                        }
                    )

    slow_buses = [
        e
        for e in events
        if e.get("record_kind") == "vehicle"
        and float((e.get("metrics") or {}).get("speed_kmh") or 0) < 12
        and (e.get("location") or {}).get("lat") is not None
    ]
    clustered: set[str] = set()
    for i, bus_a in enumerate(slow_buses):
        loc_a = bus_a.get("location") or {}
        point_a = (float(loc_a.get("lat")), float(loc_a.get("lon")))
        cluster = [bus_a]
        for bus_b in slow_buses[i + 1 :]:
            loc_b = bus_b.get("location") or {}
            point_b = (float(loc_b.get("lat")), float(loc_b.get("lon")))
            if distance_km(point_a, point_b) <= 0.5:
                cluster.append(bus_b)
        if len(cluster) >= 3:
            key = f"{round(point_a[0], 3)}_{round(point_a[1], 3)}"
            if key not in clustered:
                clustered.add(key)
                has_tomtom = any(
                    (b.get("context") or {}).get("corroboration", {}).get("near_tomtom_incident")
                    for b in cluster
                )
                anomalies.append(
                    {
                        "anomaly_type": "transit_proxy_jam",
                        "entity_id": key,
                        "event_id": cluster[0].get("event_id"),
                        "city": cluster[0].get("city"),
                        "location": f"okolice ({point_a[0]:.3f}, {point_a[1]:.3f})",
                        "message_pl": (
                            f"Spowolnienie na korytarzu — {len(cluster)} autobusów "
                            f"poniżej 12 km/h"
                            + (" (potwierdzone przez TomTom)" if has_tomtom else " (bez incydentu TomTom)")
                        ),
                        "severity": "CONGESTION",
                    }
                )

    return anomalies


def build_predictions(
    events: list[dict[str, Any]],
    history: TrafficHistory,
    *,
    horizon_minutes: int = 60,
) -> list[dict[str, Any]]:
    predictions: list[dict[str, Any]] = []

    for entity in history.all_entities():
        trend = detect_intensity_trend(entity)
        if trend and trend["predicted_in_minutes"] <= horizon_minutes:
            predictions.append(trend)

    now = datetime.now(timezone.utc)
    for event in events:
        context = event.get("context") or {}
        if context.get("time_validity") != "future":
            continue
        start = parse_event_datetime(context.get("start_time"))
        if start is None:
            continue
        minutes_until = int((start - now).total_seconds() / 60.0)
        if minutes_until < 0 or minutes_until > horizon_minutes:
            continue
        location = event.get("location") or {}
        predictions.append(
            {
                "entity_id": event.get("entity_id"),
                "event_id": event.get("event_id"),
                "location": location.get("road_name"),
                "city": event.get("city"),
                "predicted_status": event.get("status") or "CONGESTION",
                "predicted_in_minutes": minutes_until,
                "confidence": "high",
                "method": "tomtom_future",
                "message_pl": context.get("driver_summary_pl")
                or f"Planowane zdarzenie za {minutes_until} min na {location.get('road_name')}",
            }
        )

    predictions.sort(key=lambda item: item.get("predicted_in_minutes", 9999))
    return predictions


def problem_text_for_event(event: dict[str, Any], *, growing: bool = False) -> str:
    context = event.get("context") or {}
    location = event.get("location") or {}
    road = location.get("road_name") or event.get("entity_id")
    metrics = event.get("metrics") or {}

    if event.get("source_type") == "tomtom_traffic":
        delay = metrics.get("delay_sec") or 0
        prefix = "Korek narasta" if growing else "Korek"
        return f"{prefix} — {road}. Opóźnienie {delay} s."
    if event.get("record_kind") == "road_segment":
        intensity = metrics.get("intensity_vph")
        if growing:
            return f"Korek narasta na {road} — natężenie {intensity} poj./h."
        return f"Zator na {road} — natężenie {intensity} poj./h, prędkość szac. {metrics.get('speed_kmh')} km/h."
    return f"Spowolnienie w rejonie {road}."


def cause_text_for_event(event: dict[str, Any]) -> str:
    context = event.get("context") or {}
    corroboration = context.get("corroboration") or {}
    if event.get("source_type") == "tomtom_traffic":
        cause = context.get("primary_reason") or context.get("category_pl") or "Incydent drogowy (TomTom)"
        gdynia = corroboration.get("gdynia_segments") or []
        if gdynia:
            seg = gdynia[0]
            cause += f"; potwierdzone pętlą Gdynia seg. {seg.get('segment_id')} ({seg.get('intensity_vph')} poj./h)"
        probes = corroboration.get("transit_probes") or {}
        if int(probes.get("slow_bus_count") or 0) > 0:
            cause += f"; {probes['slow_bus_count']} autobusów <12 km/h w okolicy"
        return cause
    if corroboration.get("tomtom_cause"):
        return f"{corroboration['tomtom_cause']} (TomTom); natężenie lokalne: {context.get('note', 'pętle Gdynia')}"
    if event.get("record_kind") == "road_segment":
        return "Wysokie natężenie ruchu (pętle indukcyjne Gdynia)"
    if event.get("record_kind") == "vehicle":
        return "Spowolnienie widoczne w GPS autobusów miejskich"
    return "Zator drogowy"


def priority_for_event(event: dict[str, Any], score: float = 0.0) -> float:
    context = event.get("context") or {}
    base = score
    if event.get("status") == "CRITICAL":
        base += 100
    elif event.get("status") == "CONGESTION":
        base += 40
    if context.get("corridor_priority") == "high":
        base += 50
    corroboration = context.get("corroboration") or {}
    if corroboration.get("confidence") == "high":
        base += 30
    if corroboration.get("flag") == "tomtom_gap":
        base += 25
    metrics = event.get("metrics") or {}
    base += (metrics.get("delay_sec") or 0) / 10.0
    return base


def build_operational_report(
    events: list[dict[str, Any]],
    history: TrafficHistory,
    *,
    anomalies: list[dict[str, Any]] | None = None,
    predictions: list[dict[str, Any]] | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    anomalies = anomalies or []
    predictions = predictions or []
    bottlenecks = history.rank_bottlenecks(window_minutes=60, limit=limit * 2)

    event_by_entity = {history.entity_key(e): e for e in events}
    items: list[dict[str, Any]] = []

    for bottleneck in bottlenecks:
        entity_id = bottleneck["entity_id"]
        event = event_by_entity.get(entity_id)
        if event is None:
            continue
        entity = history.get_entity(entity_id)
        growing = False
        minutes_ahead = None
        if entity:
            trend = detect_intensity_trend(entity)
            if trend:
                growing = True
                minutes_ahead = trend.get("predicted_in_minutes")
        items.append(
            {
                "priority": priority_for_event(event, bottleneck["score"]),
                "location": bottleneck["location"],
                "city": bottleneck["city"],
                "problem_pl": problem_text_for_event(event, growing=growing),
                "cause_pl": cause_text_for_event(event),
                "recommendation_pl": recommend_for_event(
                    event, growing=growing, minutes_ahead=minutes_ahead
                ),
                "port_context_pl": (event.get("context") or {}).get("port_context_pl"),
                "sources": [event.get("source_type")],
                "severity": event.get("status"),
                "score": bottleneck["score"],
            }
        )

    for event in events:
        if event.get("source_type") != "tomtom_traffic":
            continue
        if (event.get("context") or {}).get("time_validity") != "present":
            continue
        if event.get("status") not in ("CRITICAL", "CONGESTION"):
            continue
        road = (event.get("location") or {}).get("road_name")
        if any(item.get("location") == road for item in items):
            continue
        items.append(
            {
                "priority": priority_for_event(event),
                "location": road,
                "city": event.get("city"),
                "problem_pl": problem_text_for_event(event),
                "cause_pl": cause_text_for_event(event),
                "recommendation_pl": recommend_for_event(event),
                "port_context_pl": (event.get("context") or {}).get("port_context_pl"),
                "sources": ["tomtom_traffic"],
                "severity": event.get("status"),
                "score": (event.get("metrics") or {}).get("delay_sec", 0) / 60.0,
            }
        )

    items.sort(key=lambda item: item.get("priority", 0), reverse=True)
    items = items[:limit]

    summary_parts = [
        f"{len(bottlenecks)} aktywnych wąskich gardeł",
        f"{len(anomalies)} anomalii",
        f"{len(predictions)} prognoz",
    ]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary_pl": ", ".join(summary_parts) + ".",
        "items": items,
        "anomaly_count": len(anomalies),
        "prediction_count": len(predictions),
    }


def event_activity_time(event: dict[str, Any]) -> datetime | None:
    context = event.get("context") or {}
    candidates: list[datetime] = []
    for raw in (context.get("last_report_time"), context.get("start_time"), event.get("timestamp")):
        parsed = parse_event_datetime(str(raw)) if raw else None
        if parsed is not None:
            candidates.append(parsed)
    return max(candidates) if candidates else None


def event_in_window(event: dict[str, Any], window_start: datetime) -> bool:
    activity = event_activity_time(event)
    if activity is not None and activity >= window_start:
        return True
    context = event.get("context") or {}
    if context.get("time_validity") == "future":
        start = parse_event_datetime(context.get("start_time"))
        if start is not None and start >= window_start:
            return True
    return False


def driver_action_for_event(event: dict[str, Any], *, growing: bool = False, minutes_ahead: int | None = None) -> str:
    return recommend_for_event(event, growing=growing, minutes_ahead=minutes_ahead)


def build_hourly_incidents_report(
    events: list[dict[str, Any]],
    history: TrafficHistory,
    *,
    window_minutes: int = 60,
    limit: int = 8,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(minutes=window_minutes)
    candidates: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    for event in events:
        if event.get("status") not in ("CRITICAL", "CONGESTION"):
            continue
        if not event_in_window(event, window_start):
            continue
        key = str(event.get("event_id") or event.get("entity_id"))
        if key in seen_keys:
            continue
        seen_keys.add(key)

        entity = history.get_entity(history.entity_key(event))
        growing = False
        minutes_ahead = None
        if entity:
            trend = detect_intensity_trend(entity)
            if trend:
                growing = True
                minutes_ahead = trend.get("predicted_in_minutes")

        context = event.get("context") or {}
        corroboration = context.get("corroboration") or {}
        metrics = event.get("metrics") or {}
        location = event.get("location") or {}
        activity = event_activity_time(event)

        candidates.append(
            {
                "priority": priority_for_event(event),
                "severity": event.get("status"),
                "city": event.get("city"),
                "location": location.get("road_name") or event.get("entity_id"),
                "problem_pl": problem_text_for_event(event, growing=growing),
                "cause_pl": cause_text_for_event(event),
                "driver_action_pl": driver_action_for_event(
                    event, growing=growing, minutes_ahead=minutes_ahead
                ),
                "confidence": corroboration.get("confidence"),
                "delay_sec": metrics.get("delay_sec"),
                "sources": list(
                    dict.fromkeys(
                        s
                        for s in (
                            event.get("source_type"),
                            "induction_loop"
                            if corroboration.get("gdynia_segments")
                            else None,
                            "public_transit_gps"
                            if int((corroboration.get("transit_probes") or {}).get("slow_bus_count") or 0) > 0
                            else None,
                        )
                        if s
                    )
                ),
                "activity_at": activity.isoformat() if activity else None,
                "time_validity": context.get("time_validity"),
                "port_context_pl": context.get("port_context_pl"),
            }
        )

    candidates.sort(key=lambda item: item.get("priority", 0), reverse=True)
    items = candidates[:limit]

    if not items:
        headline = f"Brak istotnych incydentów w ostatniej {window_minutes} min."
    elif len(items) == 1:
        headline = "1 istotny incydent w ostatniej godzinie wymaga uwagi kierowców."
    else:
        headline = f"{len(items)} istotnych incydentów w ostatniej godzinie — sprawdź rekomendacje poniżej."

    return {
        "generated_at": now.isoformat(),
        "window_minutes": window_minutes,
        "headline_pl": headline,
        "incident_count": len(items),
        "incidents": items,
    }
