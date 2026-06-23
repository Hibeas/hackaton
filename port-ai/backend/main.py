import asyncio
import hashlib
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

import httpx
import xmltodict
from aiokafka import AIOKafkaProducer
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response

from anomaly_engine import AnomalyEngine
from corridor_service import (
    build_corridor_snapshots,
    create_corridor,
    delete_corridor,
    load_corridor_config,
    update_corridor_geometry,
    update_corridor_metadata,
    update_port_geometry,
)
from observation_store import ObservationStore
from port_data_loader import port_data_store
from port_demand import analyze_cities, load_baseline
from port_events import (
    build_approach_zones,
    build_city_port_dashboard,
    build_port_summary,
    build_terminals_catalog,
)
from hybrid_delay_forecaster import DEFAULT_HORIZONS, build_forecast_response
from kafka_prediction_buffer import kafka_consumer_loop, kafka_prediction_buffer
from tomtom_service import TOMTOM_API_KEY, build_heatmap_points, collect_tomtom_events
from traffic_ml_predictor import load_model, ml_enabled, model_path, preload_model, reset_model
from voice_call_service import is_voice_call_configured, make_automated_voice_call, voice_call_mode

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GDYNIA_TRAFFIC_INTENSITIES_URL = "https://api.zdiz.gdynia.pl/ri/rest/traffic_intensities"
GDYNIA_ROAD_SEGMENTS_URL = "https://api.zdiz.gdynia.pl/ri/rest/road_segments"
SZCZECIN_VEHICLES_URL = "https://zditm.szczecin.pl/api/v1/vehicles"
GDANSK_GPS_URL = "https://ckan2.multimediagdansk.pl/gpsPositions?v=2"

REQUEST_TIMEOUT = 15.0
CACHE_REFRESH_INTERVAL_SECONDS = 30.0
GDYNIA_API_UPDATE_INTERVAL_SECONDS = 300.0
PORT_DATA_REFRESH_INTERVAL_SECONDS = 300.0
KAFKA_BOOTSTRAP_SERVERS = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:8081")
KAFKA_TOPIC = os.environ.get("KAFKA_TOPIC", "port-traffic-events")
KAFKA_PUBLISH_ON_REFRESH = os.environ.get("KAFKA_PUBLISH_ON_REFRESH", "true").lower() in {
    "1",
    "true",
    "yes",
}

kafka_producer: AIOKafkaProducer | None = None
kafka_consumer_task: asyncio.Task[None] | None = None
cache_refresh_task: asyncio.Task[None] | None = None
gdynia_watch_task: asyncio.Task[None] | None = None
port_data_refresh_task: asyncio.Task[None] | None = None


class TrafficCache:
    def __init__(self) -> None:
        self.primary_events: list[dict[str, Any]] = []
        self.context_events: list[dict[str, Any]] = []
        self.corridor_snapshots: list[dict[str, Any]] = []
        self.engine_events: list[dict[str, Any]] = []
        self.updated_at: datetime | None = None
        self.gdynia_fingerprint: str | None = None
        self.gdynia_timer_recalibrated_at: datetime | None = None
        self.gdynia_changed_on_last_refresh: bool = False
        self._lock = asyncio.Lock()
        self._refresh_lock = asyncio.Lock()

    def age_seconds(self) -> float | None:
        if self.updated_at is None:
            return None
        return (datetime.now(timezone.utc) - self.updated_at).total_seconds()

    async def refresh(self, *, is_startup: bool = False) -> bool:
        """Refresh cache. Returns True when Gdynia API data changed."""
        async with self._refresh_lock:
            gdynia_raw = await fetch_gdynia_intensities_raw()
            incoming_fingerprint = gdynia_fingerprint_from_raw(gdynia_raw)
            gdynia_changed = (
                not is_startup
                and self.gdynia_fingerprint is not None
                and incoming_fingerprint is not None
                and incoming_fingerprint != self.gdynia_fingerprint
            )

            primary_events, context_events = await asyncio.gather(
                collect_tomtom_events(),
                collect_port_traffic(),
            )
            for event in context_events:
                event["data_tier"] = "context"

            if incoming_fingerprint is None:
                incoming_fingerprint = gdynia_fingerprint_from_events(context_events)

            snapshots = build_corridor_snapshots(
                primary_events,
                context_events,
                port_demand_baseline,
            )
            observation_store.append_batch(snapshots)
            engine_events = anomaly_engine.evaluate(snapshots)

            if KAFKA_PUBLISH_ON_REFRESH:
                await publish_events_to_kafka(primary_events + context_events)
                await publish_corridor_snapshots_to_kafka(snapshots)

            for snapshot in snapshots:
                kafka_prediction_buffer.ingest_snapshot(snapshot)

            async with self._lock:
                self.primary_events = primary_events
                self.context_events = context_events
                self.corridor_snapshots = snapshots
                self.engine_events = engine_events
                self.updated_at = datetime.now(timezone.utc)

            self.gdynia_changed_on_last_refresh = gdynia_changed
            self.gdynia_fingerprint = incoming_fingerprint

            if is_startup:
                self.gdynia_timer_recalibrated_at = datetime.now(timezone.utc)
                logger.info(
                    "Initial cache refresh on startup (TomTom %s, ZTM %s, engine events %s)",
                    len(primary_events),
                    len(context_events),
                    len(engine_events),
                )
            elif gdynia_changed:
                self.gdynia_timer_recalibrated_at = datetime.now(timezone.utc)
                logger.info(
                    "Gdynia API data changed; cache refreshed (TomTom %s, ZTM %s)",
                    len(primary_events),
                    len(context_events),
                )
            else:
                logger.info(
                    "Traffic cache refreshed (TomTom %s, ZTM %s, engine events %s)",
                    len(primary_events),
                    len(context_events),
                    len(engine_events),
                )

            return gdynia_changed

    async def get_snapshot(
        self,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], datetime | None]:
        async with self._lock:
            return list(self.primary_events), list(self.context_events), self.updated_at

    async def get_engine_state(
        self,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], datetime | None]:
        async with self._lock:
            return (
                list(self.corridor_snapshots),
                list(self.engine_events),
                self.updated_at,
            )


traffic_cache = TrafficCache()
observation_store = ObservationStore()
anomaly_engine = AnomalyEngine(observation_store)

# Static offline baseline of expected port truck demand (from CODECO gate moves).
# Loaded once at import; rebuild via build_demand_baseline.py when CODECO updates.
port_demand_baseline = load_baseline()


async def cache_refresh_loop() -> None:
    while True:
        await asyncio.sleep(CACHE_REFRESH_INTERVAL_SECONDS)
        try:
            await traffic_cache.refresh()
        except Exception as exc:
            logger.warning("Background cache refresh failed: %s", exc)


async def gdynia_watch_loop() -> None:
    """Poll Gdynia intensities and refresh immediately when API data changes."""
    while True:
        await asyncio.sleep(CACHE_REFRESH_INTERVAL_SECONDS)
        try:
            gdynia_raw = await fetch_gdynia_intensities_raw()
            incoming_fingerprint = gdynia_fingerprint_from_raw(gdynia_raw)
            if (
                traffic_cache.gdynia_fingerprint is not None
                and incoming_fingerprint is not None
                and incoming_fingerprint != traffic_cache.gdynia_fingerprint
            ):
                await traffic_cache.refresh()
        except Exception as exc:
            logger.warning("Gdynia watch loop failed: %s", exc)


async def port_data_refresh_loop() -> None:
    """Refresh PCS Excel → SQLite cache for terminal/port operations."""
    while True:
        try:
            await asyncio.to_thread(port_data_store.refresh)
            logger.info(
                "Port PCS data refreshed (%s moves, %s calls)",
                len(port_data_store.container_moves),
                len(port_data_store.port_calls),
            )
        except Exception as exc:
            logger.warning("Port PCS refresh failed: %s", exc)
        await asyncio.sleep(PORT_DATA_REFRESH_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(_: FastAPI):
    global kafka_producer, kafka_consumer_task, cache_refresh_task, gdynia_watch_task, port_data_refresh_task
    producer = AIOKafkaProducer(
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        value_serializer=lambda value: json.dumps(value, ensure_ascii=False).encode("utf-8"),
        key_serializer=lambda key: key.encode("utf-8") if key else None,
    )
    try:
        await producer.start()
        kafka_producer = producer
        logger.info("Kafka producer connected to %s", KAFKA_BOOTSTRAP_SERVERS)
    except Exception as exc:
        kafka_producer = None
        logger.warning("Kafka producer unavailable: %s", exc)

    try:
        await asyncio.to_thread(port_data_store.refresh)
        logger.info("Initial port PCS data load complete")
    except Exception as exc:
        logger.warning("Initial port PCS data load failed: %s", exc)

    try:
        await traffic_cache.refresh(is_startup=True)
    except Exception as exc:
        logger.warning("Initial cache refresh on startup failed: %s", exc)

    try:
        loaded = await asyncio.to_thread(preload_model)
        if loaded is None and ml_enabled():
            logger.warning("Traffic ML model failed to preload from %s", model_path())
        else:
            logger.info("Traffic ML model preloaded: %s", loaded is not None)
    except Exception as exc:
        logger.warning("Traffic ML preload failed: %s", exc)

    cache_refresh_task = asyncio.create_task(cache_refresh_loop())
    gdynia_watch_task = asyncio.create_task(gdynia_watch_loop())
    port_data_refresh_task = asyncio.create_task(port_data_refresh_loop())
    kafka_consumer_task = asyncio.create_task(kafka_consumer_loop())
    try:
        yield
    finally:
        for task_name, task in (
            ("cache_refresh_task", cache_refresh_task),
            ("gdynia_watch_task", gdynia_watch_task),
            ("port_data_refresh_task", port_data_refresh_task),
            ("kafka_consumer_task", kafka_consumer_task),
        ):
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        cache_refresh_task = None
        gdynia_watch_task = None
        port_data_refresh_task = None
        kafka_consumer_task = None
        if kafka_producer is not None:
            await kafka_producer.stop()
            kafka_producer = None


app = FastAPI(title="Port Traffic API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def ensure_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


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


def traffic_status(speed_kmh: float) -> str:
    if speed_kmh < 12:
        return "CRITICAL"
    if speed_kmh < 25:
        return "CONGESTION"
    return "CLEAR"


def traffic_status_for_loop(intensity_vph: float) -> str:
    """Port induction loops — high volume is normal; flag only extreme saturation."""
    if intensity_vph >= 2200:
        return "CRITICAL"
    if intensity_vph >= 1850:
        return "CONGESTION"
    return "CLEAR"


def estimate_speed_from_intensity(intensity_vph: float) -> float:
    """Heuristic speed estimate when only loop intensity is available."""
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


def segment_centroid(geometry: dict[str, Any]) -> tuple[float, float]:
    coordinates = geometry.get("coordinates") or []
    if not coordinates:
        return 0.0, 0.0
    lons = [float(point[0]) for point in coordinates]
    lats = [float(point[1]) for point in coordinates]
    return sum(lats) / len(lats), sum(lons) / len(lons)


def parse_gdynia_payload(raw: str) -> Any:
    """Parse Gdynia response as DATEX II XML (xmltodict) or JSON fallback."""
    stripped = raw.strip()
    if stripped.startswith("<"):
        return xmltodict.parse(stripped)
    return json.loads(stripped)


def extract_datex_records(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Walk DATEX II xmltodict tree and collect measurement-like records."""
    records: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            keys = {k.lower() for k in node}
            if {"intensity", "roadsegmentid"} <= keys or {"eventid", "roadsegmentid"} <= keys:
                records.append(node)
            elif "vehicleflow" in keys or "trafficflow" in keys:
                records.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return records


def normalize_gdynia_intensity_record(record: dict[str, Any]) -> dict[str, Any]:
    event_id = record.get("eventId") or record.get("eventid") or record.get("@id")
    segment_id = record.get("roadSegmentId") or record.get("roadsegmentid") or record.get("id")
    intensity = record.get("intensity") or record.get("vehicleFlow") or record.get("vehicleflow")
    measure_time = record.get("measureTime") or record.get("measuretime") or record.get("time")

    if isinstance(intensity, dict):
        intensity = intensity.get("#text") or intensity.get("value")

    intensity_vph = float(intensity) if intensity is not None else 0.0
    speed_kmh = estimate_speed_from_intensity(intensity_vph)
    segment_key = str(segment_id) if segment_id is not None else "unknown"

    return {
        "event_id": f"gdynia_seg_{segment_key}",
        "segment_id": segment_key,
        "timestamp": to_iso_timestamp(str(measure_time) if measure_time else None),
        "intensity_vph": intensity_vph,
        "speed_kmh": speed_kmh,
        "raw_event_id": str(event_id) if event_id is not None else segment_key,
    }


def parse_gdynia_intensities(raw: str | None) -> list[dict[str, Any]]:
    if not raw:
        return []
    try:
        payload = parse_gdynia_payload(raw)
    except Exception as exc:
        logger.warning("Failed to parse Gdynia intensities: %s", exc)
        return []

    if isinstance(payload, list):
        records = payload
    elif isinstance(payload, dict):
        records = extract_datex_records(payload)
        if not records:
            for key in ("trafficIntensities", "intensities", "items", "data"):
                if key in payload:
                    records = ensure_list(payload[key])
                    break
    else:
        return []

    return [normalize_gdynia_intensity_record(item) for item in records if isinstance(item, dict)]


def parse_gdynia_segments(raw: str | None) -> dict[str, dict[str, Any]]:
    if not raw:
        return {}
    try:
        payload = parse_gdynia_payload(raw)
    except Exception as exc:
        logger.warning("Failed to parse Gdynia road segments: %s", exc)
        return {}

    segments: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        if "road_segments" in payload:
            segments = ensure_list(payload["road_segments"])
        else:
            segments = extract_datex_records(payload)
            if not segments:
                for key in ("roadSegments", "segments", "items"):
                    if key in payload:
                        segments = ensure_list(payload[key])
                        break
    elif isinstance(payload, list):
        segments = payload

    segment_map: dict[str, dict[str, Any]] = {}
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        segment_id = segment.get("id") or segment.get("@id") or segment.get("roadSegmentId")
        if segment_id is None:
            continue
        segment_map[str(segment_id)] = segment
    return segment_map


def normalize_segment_geometry(geometry: dict[str, Any]) -> dict[str, Any] | None:
    raw_coordinates = geometry.get("coordinates") or []
    coordinates: list[list[float]] = []
    for point in raw_coordinates:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        try:
            lon = float(point[0])
            lat = float(point[1])
        except (TypeError, ValueError):
            continue
        coordinates.append([lon, lat])
    if len(coordinates) < 2:
        return None
    return {
        "type": geometry.get("type") or "LineString",
        "coordinates": coordinates,
    }


def build_gdynia_events(
    intensities: list[dict[str, Any]],
    segments: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for item in intensities:
        segment = segments.get(item["segment_id"], {})
        raw_geometry = segment.get("geometry") or {}
        geometry = normalize_segment_geometry(raw_geometry)
        lat, lon = segment_centroid(raw_geometry)
        events.append(
            {
                "event_id": item["event_id"],
                "record_kind": "road_segment",
                "entity_id": item["segment_id"],
                "city": "Gdynia",
                "source_type": "induction_loop",
                "timestamp": item["timestamp"],
                "location": {
                    "lat": lat,
                    "lon": lon,
                    "road_name": f"Segment {item['segment_id']}",
                },
                "geometry": geometry,
                "metrics": {
                    "speed_kmh": item["speed_kmh"],
                    "intensity_vph": item["intensity_vph"],
                    "is_bus_stop": False,
                },
                "status": traffic_status_for_loop(item["intensity_vph"]),
            }
        )
    return events


def build_szczecin_events(raw: str | None) -> list[dict[str, Any]]:
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse Szczecin vehicles: %s", exc)
        return []

    vehicles = payload.get("data") if isinstance(payload, dict) else payload
    events: list[dict[str, Any]] = []
    for vehicle in ensure_list(vehicles):
        if not isinstance(vehicle, dict):
            continue
        vehicle_id = vehicle.get("vehicle_id") or vehicle.get("vehicle_number") or "unknown"
        speed_kmh = float(vehicle.get("velocity") or 0)
        next_stop = vehicle.get("next_stop")
        previous_stop = vehicle.get("previous_stop")
        is_bus_stop = speed_kmh == 0 or bool(vehicle.get("stuck"))
        road_name = f"Line {vehicle.get('line_number', '?')} ({vehicle.get('direction', 'unknown')})"
        if is_bus_stop and next_stop:
            road_name = f"{road_name} @ {next_stop}"
        elif previous_stop:
            road_name = f"{road_name} near {previous_stop}"

        line_number = vehicle.get("line_number")
        direction = vehicle.get("direction")
        events.append(
            {
                "event_id": f"szczecin_veh_{vehicle_id}",
                "record_kind": "vehicle",
                "entity_id": str(vehicle_id),
                "city": "Szczecin",
                "source_type": "public_transit_gps",
                "timestamp": to_iso_timestamp(vehicle.get("updated_at")),
                "location": {
                    "lat": float(vehicle.get("latitude") or 0),
                    "lon": float(vehicle.get("longitude") or 0),
                    "road_name": road_name,
                },
                "geometry": None,
                "metrics": {
                    "speed_kmh": speed_kmh,
                    "intensity_vph": None,
                    "is_bus_stop": is_bus_stop,
                    "line": str(line_number) if line_number is not None else None,
                    "direction": str(direction) if direction is not None else None,
                    "next_stop": str(next_stop) if next_stop else None,
                    "previous_stop": str(previous_stop) if previous_stop else None,
                },
                "status": traffic_status(speed_kmh),
            }
        )
    return events


def build_gdansk_events(raw: str | None) -> list[dict[str, Any]]:
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse Gdansk GPS: %s", exc)
        return []

    vehicles = payload.get("vehicles") if isinstance(payload, dict) else payload
    events: list[dict[str, Any]] = []
    for vehicle in ensure_list(vehicles):
        if not isinstance(vehicle, dict):
            continue
        vehicle_id = vehicle.get("vehicleId") or vehicle.get("vehicleCode") or "unknown"
        speed_kmh = float(vehicle.get("speed") or 0)
        route = vehicle.get("routeShortName") or vehicle.get("routeId") or "?"
        headsign = vehicle.get("headsign") or ""
        is_bus_stop = speed_kmh == 0
        road_name = f"Line {route}"
        if headsign:
            road_name = f"{road_name} -> {headsign}"

        timestamp = vehicle.get("generated") or payload.get("lastUpdate")
        events.append(
            {
                "event_id": f"gdansk_veh_{vehicle_id}",
                "record_kind": "vehicle",
                "entity_id": str(vehicle_id),
                "city": "Gdansk",
                "source_type": "public_transit_gps",
                "timestamp": to_iso_timestamp(timestamp),
                "location": {
                    "lat": float(vehicle.get("lat") or 0),
                    "lon": float(vehicle.get("lon") or 0),
                    "road_name": road_name,
                },
                "geometry": None,
                "metrics": {
                    "speed_kmh": speed_kmh,
                    "intensity_vph": None,
                    "is_bus_stop": is_bus_stop,
                    "line": str(route) if route is not None else None,
                    "headsign": str(headsign) if headsign else None,
                },
                "status": traffic_status(speed_kmh),
            }
        )
    return events


async def fetch_text(client: httpx.AsyncClient, url: str, label: str) -> str | None:
    try:
        response = await client.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.text
    except httpx.TimeoutException:
        logger.warning("%s API timeout after %.0fs", label, REQUEST_TIMEOUT)
    except httpx.HTTPStatusError as exc:
        logger.warning("%s API HTTP error: %s", label, exc.response.status_code)
    except Exception as exc:
        logger.warning("%s API request failed: %s", label, exc)
    return None


async def fetch_gdynia_intensities_raw() -> str | None:
    async with httpx.AsyncClient(follow_redirects=True) as client:
        return await fetch_text(client, GDYNIA_TRAFFIC_INTENSITIES_URL, "Gdynia intensities")


def gdynia_fingerprint_from_raw(raw: str | None) -> str | None:
    if not raw:
        return None
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def gdynia_fingerprint_from_events(events: list[dict[str, Any]]) -> str | None:
    gdynia_events = [event for event in events if event.get("city") == "Gdynia"]
    if not gdynia_events:
        return None
    parts = sorted(
        (
            event.get("event_id"),
            event.get("timestamp"),
            event.get("metrics", {}).get("intensity_vph"),
        )
        for event in gdynia_events
    )
    payload = json.dumps(parts, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def collect_port_traffic() -> list[dict[str, Any]]:
    async with httpx.AsyncClient(follow_redirects=True) as client:
        (
            gdynia_intensities_raw,
            gdynia_segments_raw,
            szczecin_raw,
            gdansk_raw,
        ) = await asyncio.gather(
            fetch_text(client, GDYNIA_TRAFFIC_INTENSITIES_URL, "Gdynia intensities"),
            fetch_text(client, GDYNIA_ROAD_SEGMENTS_URL, "Gdynia segments"),
            fetch_text(client, SZCZECIN_VEHICLES_URL, "Szczecin"),
            fetch_text(client, GDANSK_GPS_URL, "Gdansk"),
        )

    intensities = parse_gdynia_intensities(gdynia_intensities_raw)
    segments = parse_gdynia_segments(gdynia_segments_raw)

    unified: list[dict[str, Any]] = []
    unified.extend(build_gdynia_events(intensities, segments))
    unified.extend(build_szczecin_events(szczecin_raw))
    unified.extend(build_gdansk_events(gdansk_raw))
    return unified


def parse_event_datetime(raw: str) -> datetime | None:
    normalized = raw.strip().replace("Z", "+00:00")
    if " " in normalized and "T" not in normalized:
        normalized = normalized.replace(" ", "T", 1)
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def build_city_source_metadata(
    events: list[dict[str, Any]],
    city: str,
    record_kind: str,
) -> dict[str, Any]:
    city_events = [event for event in events if event.get("city") == city]
    timestamps: list[datetime] = []
    for event in city_events:
        timestamp = event.get("timestamp")
        if not timestamp:
            continue
        parsed = parse_event_datetime(str(timestamp))
        if parsed is not None:
            timestamps.append(parsed)

    return {
        "record_kind": record_kind,
        "event_count": len(city_events),
        "last_timestamp": max(timestamps).isoformat() if timestamps else None,
    }


def build_gdynia_source_metadata(events: list[dict[str, Any]]) -> dict[str, Any]:
    measure_times: list[datetime] = []
    for event in events:
        if event.get("city") != "Gdynia":
            continue
        timestamp = event.get("timestamp")
        if not timestamp:
            continue
        parsed = parse_event_datetime(str(timestamp))
        if parsed is not None:
            measure_times.append(parsed)

    now = datetime.now(timezone.utc)
    if not measure_times:
        return {
            "record_kind": "road_segment",
            "last_measure_at": None,
            "next_update_at": None,
            "seconds_until_update": None,
            "update_interval_seconds": GDYNIA_API_UPDATE_INTERVAL_SECONDS,
            "event_count": 0,
            "last_timestamp": None,
            "is_overdue": False,
        }

    last_measure_at = max(measure_times)
    next_update_at = last_measure_at + timedelta(seconds=GDYNIA_API_UPDATE_INTERVAL_SECONDS)
    seconds_until_update = max(0.0, (next_update_at - now).total_seconds())

    return {
        "record_kind": "road_segment",
        "last_measure_at": last_measure_at.isoformat(),
        "last_timestamp": last_measure_at.isoformat(),
        "next_update_at": next_update_at.isoformat(),
        "seconds_until_update": round(seconds_until_update),
        "update_interval_seconds": GDYNIA_API_UPDATE_INTERVAL_SECONDS,
        "event_count": len(measure_times),
        "is_overdue": now >= next_update_at,
    }


def enrich_gdynia_metadata(events: list[dict[str, Any]]) -> dict[str, Any]:
    metadata = build_gdynia_source_metadata(events)
    metadata["data_fingerprint"] = traffic_cache.gdynia_fingerprint
    metadata["data_changed"] = traffic_cache.gdynia_changed_on_last_refresh
    metadata["timer_calibrated_at"] = (
        traffic_cache.gdynia_timer_recalibrated_at.isoformat()
        if traffic_cache.gdynia_timer_recalibrated_at
        else None
    )
    return metadata


async def publish_events_to_kafka(events: list[dict[str, Any]]) -> int:
    if kafka_producer is None:
        logger.warning("Skipping Kafka publish: producer is not connected")
        return 0

    published = 0
    for event in events:
        try:
            await kafka_producer.send_and_wait(
                KAFKA_TOPIC,
                value=event,
                key=event.get("event_id"),
            )
            published += 1
        except Exception as exc:
            logger.warning(
                "Failed to publish event %s to Kafka: %s",
                event.get("event_id"),
                exc,
            )
    logger.info("Published %s/%s events to topic %s", published, len(events), KAFKA_TOPIC)
    return published


def corridor_snapshot_kafka_message(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "record_kind": "corridor_snapshot",
        "event_id": f"corridor_snapshot_{snapshot.get('corridor_id')}_{snapshot.get('timestamp', '')}",
        "corridor_id": snapshot.get("corridor_id"),
        "port_id": snapshot.get("port_id"),
        "port_name": snapshot.get("port_name"),
        "corridor_name": snapshot.get("corridor_name"),
        "timestamp": snapshot.get("timestamp"),
        "metrics": snapshot.get("metrics") or {},
    }


async def publish_corridor_snapshots_to_kafka(snapshots: list[dict[str, Any]]) -> int:
    if kafka_producer is None or not snapshots:
        return 0
    published = 0
    for snapshot in snapshots:
        message = corridor_snapshot_kafka_message(snapshot)
        try:
            await kafka_producer.send_and_wait(
                KAFKA_TOPIC,
                value=message,
                key=str(snapshot.get("corridor_id") or ""),
            )
            published += 1
        except Exception as exc:
            logger.warning(
                "Failed to publish corridor snapshot %s to Kafka: %s",
                snapshot.get("corridor_id"),
                exc,
            )
    if published:
        logger.info("Published %s corridor snapshots to topic %s", published, KAFKA_TOPIC)
    return published


def parse_horizons_param(raw: str) -> tuple[int, ...]:
    values: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            minute = int(part)
        except ValueError:
            continue
        if 5 <= minute <= 360:
            values.append(minute)
    return tuple(sorted(set(values))) if values else DEFAULT_HORIZONS


@app.get("/api/v1/port-traffic")
async def get_port_traffic(
    publish_kafka: bool = Query(default=True, description="Publish events to Kafka"),
    use_cache: bool = Query(default=False, description="Return cached data instead of live fetch"),
) -> list[dict[str, Any]] | dict[str, Any]:
    if use_cache:
        return await get_map_data()

    events = await collect_port_traffic()
    if publish_kafka:
        await publish_events_to_kafka(events)
    return events


@app.get("/api/v1/map-data")
async def get_map_data() -> dict[str, Any]:
    primary, context, updated_at = await traffic_cache.get_snapshot()
    if not primary and not context:
        await traffic_cache.refresh(is_startup=True)
        primary, context, updated_at = await traffic_cache.get_snapshot()

    road_events = primary + context
    terminals_catalog = build_terminals_catalog(port_data_store)
    approach_zones = build_approach_zones(port_data_store, traffic_events=road_events)
    city_port_dashboard = build_city_port_dashboard(port_data_store, traffic_events=road_events)
    delay_forecasts = build_forecast_response(
        observation_store=observation_store,
        horizons=DEFAULT_HORIZONS,
    )

    return {
        "primary": {
            "source": "tomtom",
            "events": primary,
            "incident_count": len(primary),
        },
        "context": {
            "source": "ztm",
            "events": context,
        },
        "heatmap": {
            "source": "tomtom",
            "points": build_heatmap_points(primary),
            "flow_tile_url": "/api/v1/tomtom/tiles/flow/relative0/{z}/{x}/{y}.png",
        },
        "port_operations": {
            "summary": build_port_summary(port_data_store, traffic_events=road_events),
            "terminals_catalog": terminals_catalog,
            "approach_zones": approach_zones,
            "city_port_dashboard": city_port_dashboard,
            "updated_at": port_data_store.updated_at.isoformat() if port_data_store.updated_at else None,
        },
        "events": primary,
        "cached_at": updated_at.isoformat() if updated_at else None,
        "age_seconds": traffic_cache.age_seconds(),
        "refresh_interval_seconds": CACHE_REFRESH_INTERVAL_SECONDS,
        "delay_forecasts": delay_forecasts,
        "sources": {
            "tomtom": {
                "incident_count": len(primary),
                "cities": sorted({event.get("city") for event in primary if event.get("city")}),
            },
            "gdynia": enrich_gdynia_metadata(context),
            "szczecin": build_city_source_metadata(context, "Szczecin", "vehicle"),
            "gdansk": build_city_source_metadata(context, "Gdansk", "vehicle"),
        },
    }


ALLOWED_FLOW_TILE_STYLES = frozenset({"relative0", "relative", "absolute", "relative-delay0"})


@app.get("/api/v1/tomtom/tiles/flow/{style}/{z}/{x}/{y}.png")
async def get_tomtom_flow_tile(style: str, z: int, x: int, y: int) -> Response:
    """Proxy TomTom Traffic Flow raster tiles (live road congestion overlay)."""
    if style not in ALLOWED_FLOW_TILE_STYLES:
        raise HTTPException(status_code=400, detail="Unsupported flow tile style")

    url = f"https://api.tomtom.com/traffic/map/4/tile/flow/{style}/{z}/{x}/{y}.png"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                params={"key": TOMTOM_API_KEY},
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail="TomTom flow tile unavailable",
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="TomTom flow tile fetch failed") from exc

    return Response(content=response.content, media_type="image/png")


@app.get("/api/v1/engine/events")
async def get_engine_events() -> dict[str, Any]:
    """Structured port anomaly events from the detection engine."""
    snapshots, events, updated_at = await traffic_cache.get_engine_state()
    if not snapshots:
        await traffic_cache.refresh(is_startup=True)
        snapshots, events, updated_at = await traffic_cache.get_engine_state()

    return {
        "evaluated_at": updated_at.isoformat() if updated_at else None,
        "observation_count": observation_store.corridor_count(),
        "events": events,
        "active_count": len(events),
    }


@app.get("/api/v1/engine/bottlenecks")
async def get_engine_bottlenecks(
    window: int = Query(default=60, ge=15, le=120, description="Ranking window in minutes"),
) -> dict[str, Any]:
    """Largest access-road bottlenecks over the recent window."""
    _, _, updated_at = await traffic_cache.get_engine_state()
    if updated_at is None:
        await traffic_cache.refresh(is_startup=True)

    bottlenecks = anomaly_engine.bottlenecks_last_hour()
    return {
        "window_minutes": window,
        "evaluated_at": updated_at.isoformat() if updated_at else None,
        "bottlenecks": bottlenecks,
    }


@app.get("/api/v1/engine/corridors")
async def get_engine_corridors() -> dict[str, Any]:
    """Current per-corridor metrics snapshot (live pulse)."""
    snapshots, events, updated_at = await traffic_cache.get_engine_state()
    if not snapshots:
        await traffic_cache.refresh(is_startup=True)
        snapshots, events, updated_at = await traffic_cache.get_engine_state()

    return {
        "evaluated_at": updated_at.isoformat() if updated_at else None,
        "corridors": snapshots,
        "related_events": events,
    }


@app.get("/api/v1/engine/forecast")
async def get_engine_forecast(
    horizons: str = Query(
        default="10,15,20,30,45,60,120,180",
        description="Comma-separated forecast horizons in minutes",
    ),
    port_id: str | None = Query(default=None),
    corridor_id: str | None = Query(default=None),
) -> dict[str, Any]:
    """Hybrid delay forecast per corridor (Kafka trend <=30 min, ML >30 min)."""
    _, _, updated_at = await traffic_cache.get_engine_state()
    if updated_at is None:
        await traffic_cache.refresh(is_startup=True)
    parsed_horizons = parse_horizons_param(horizons)
    return build_forecast_response(
        observation_store=observation_store,
        horizons=parsed_horizons,
        port_id=port_id,
        corridor_id=corridor_id,
    )


class CorridorGeometryUpdate(BaseModel):
    bbox: dict[str, float] = Field(
        ...,
        description="Axis-aligned bounding box derived from the drawn polygon",
    )
    polygon: list[list[float]] | None = Field(
        default=None,
        description="Optional polygon vertices as [lat, lon] pairs",
    )


class CorridorMetadataUpdate(BaseModel):
    name: str | None = None
    city: str | None = None
    geofence_type: str | None = None
    business_priority: str | None = None
    logistics_weight: int | None = Field(default=None, ge=1, le=10)
    impacts_port_access: bool | None = None
    terminals: list[str] | None = None


class CorridorCreateRequest(BaseModel):
    id: str
    name: str
    city: str | None = None
    geofence_type: str = "APPROACH_CORRIDOR"
    business_priority: str = "HIGH"
    logistics_weight: int = Field(default=7, ge=1, le=10)
    impacts_port_access: bool = True
    bbox: dict[str, float]
    polygon: list[list[float]] | None = None
    terminals: list[str] | None = None


def _validate_bbox(bbox: dict[str, float]) -> None:
    required = ("min_lat", "max_lat", "min_lon", "max_lon")
    if not all(key in bbox for key in required):
        raise HTTPException(status_code=422, detail=f"bbox must include {required}")


@app.get("/api/v1/engine/corridor-config")
async def get_corridor_config() -> dict[str, Any]:
    """Full corridor configuration (bbox + optional polygon per segment)."""
    return load_corridor_config()


@app.patch("/api/v1/engine/ports/{port_id}/geometry")
async def patch_port_geometry(port_id: str, body: CorridorGeometryUpdate) -> dict[str, Any]:
    """Update port-level geofence bbox/polygon."""
    _validate_bbox(body.bbox)
    try:
        update_port_geometry(port_id, body.bbox, body.polygon)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "port_id": port_id}


@app.patch("/api/v1/engine/corridors/{corridor_id}/geometry")
async def patch_corridor_geometry(
    corridor_id: str,
    body: CorridorGeometryUpdate,
) -> dict[str, Any]:
    """Update a corridor bbox/polygon — dev tool for manual map calibration."""
    _validate_bbox(body.bbox)
    try:
        update_corridor_geometry(corridor_id, body.bbox, body.polygon)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "corridor_id": corridor_id}


@app.patch("/api/v1/engine/corridors/{corridor_id}")
async def patch_corridor_metadata_endpoint(
    corridor_id: str,
    body: CorridorMetadataUpdate,
) -> dict[str, Any]:
    """Update corridor name, type, priority, terminals."""
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=422, detail="No metadata fields provided")
    try:
        update_corridor_metadata(corridor_id, updates)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "corridor_id": corridor_id}


@app.post("/api/v1/engine/ports/{port_id}/corridors")
async def post_corridor(port_id: str, body: CorridorCreateRequest) -> dict[str, Any]:
    """Create a new corridor geofence under a port."""
    _validate_bbox(body.bbox)
    try:
        create_corridor(port_id, body.model_dump())
    except ValueError as exc:
        status = 409 if "already exists" in str(exc) else 404
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return {"ok": True, "port_id": port_id, "corridor_id": body.id}


@app.delete("/api/v1/engine/corridors/{corridor_id}")
async def remove_corridor(corridor_id: str) -> dict[str, Any]:
    """Delete a corridor geofence."""
    try:
        delete_corridor(corridor_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "corridor_id": corridor_id}


@app.get("/api/v1/anomalies")
async def get_anomalies() -> dict[str, Any]:
    """Classify TomTom incidents against port demand, with ZTM as context."""
    primary, context, _ = await traffic_cache.get_snapshot()
    if not primary and not context:
        await traffic_cache.refresh(is_startup=True)
        primary, context, _ = await traffic_cache.get_snapshot()
    return analyze_cities(port_demand_baseline, primary, context)


@app.get("/")
async def map_page() -> FileResponse:
    return FileResponse("map.html")


@app.get("/map")
async def map_page_alias() -> FileResponse:
    return FileResponse("map.html")


@app.post("/api/v1/engine/ml/reload")
async def reload_ml_model() -> dict[str, Any]:
    """Reset and reload the on-disk delay regressor (no buffer / cache reuse)."""
    reset_model()
    model = await asyncio.to_thread(lambda: load_model(force=True))
    return {
        "ok": model is not None,
        "enabled": ml_enabled(),
        "model_path": str(model_path()),
        "loaded": model is not None,
    }


class VoiceDemoCallRequest(BaseModel):
    to_number: str | None = Field(default=None, description="E.164 override; defaults to VOICE_CALL_DEMO_TO")
    message: str | None = Field(default=None, max_length=500)


@app.post("/api/v1/voice/demo-call")
async def trigger_voice_demo_call(body: VoiceDemoCallRequest | None = None) -> dict[str, Any]:
    """Temporary demo: outbound voice alert via ElevenLabs + Twilio."""
    if not is_voice_call_configured():
        raise HTTPException(status_code=503, detail="voice_not_configured")

    to_number = (body.to_number if body and body.to_number else os.environ.get("VOICE_CALL_DEMO_TO", "")).strip()
    if not to_number:
        raise HTTPException(status_code=400, detail="voice_demo_to_missing")

    message = (
        body.message
        if body and body.message
        else "Uwaga! Jedzie dziekan. Przygotujcie się — za chwilę wchodzi na salę hackathonu."
    )

    try:
        return await make_automated_voice_call(to_number, message)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Voice demo call failed")
        raise HTTPException(status_code=500, detail="voice_call_failed") from exc


@app.get("/health")
async def health() -> dict[str, Any]:
    model = load_model()
    return {
        "status": "ok",
        "database": observation_store.backend_name,
        "observation_count": observation_store.corridor_count(),
        "ml": {
            "enabled": ml_enabled(),
            "model_path": str(model_path()),
            "loaded": model is not None,
        },
        "kafka": {
            "connected": kafka_producer is not None,
            "bootstrap": KAFKA_BOOTSTRAP_SERVERS,
            "topic": KAFKA_TOPIC,
            "publish_on_refresh": KAFKA_PUBLISH_ON_REFRESH,
            "consumer_running": kafka_consumer_task is not None and not kafka_consumer_task.done(),
            "prediction_buffer": kafka_prediction_buffer.status(),
        },
        "voice": {
            "configured": is_voice_call_configured(),
            "mode": voice_call_mode(),
        },
    }
