import asyncio
import hashlib
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import xmltodict
from aiokafka import AIOKafkaProducer
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from anomaly_engine import AnomalyEngine
from corridor_service import build_corridor_snapshots, load_corridor_config
from observation_store import ObservationStore
from port_data_loader import port_data_store
from port_events import (
    build_approach_zones,
    build_city_port_dashboard,
    build_codeco_hourly_24h,
    build_port_map_events,
    build_port_summary,
    build_terminals_catalog,
)
from port_demand import analyze_cities, load_baseline
from traffic_fusion import fuse_traffic_events
from traffic_history import TrafficHistory
from traffic_intelligence import (
    build_hourly_incidents_report,
    build_operational_report,
    build_predictions,
    collect_segment_trends,
    detect_anomalies,
)
from tomtom_traffic import collect_tomtom_events, get_tomtom_api_key
from tomtom_routing import build_route_forecast, compute_bypass, routing_enabled

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GDYNIA_TRAFFIC_INTENSITIES_URL = "https://api.zdiz.gdynia.pl/ri/rest/traffic_intensities"
GDYNIA_ROAD_SEGMENTS_URL = "https://api.zdiz.gdynia.pl/ri/rest/road_segments"
SZCZECIN_VEHICLES_URL = "https://zditm.szczecin.pl/api/v1/vehicles"
GDANSK_GPS_URL = "https://ckan2.multimediagdansk.pl/gpsPositions?v=2"

REQUEST_TIMEOUT = 15.0
CACHE_REFRESH_INTERVAL_SECONDS = 30.0
PORT_DATA_REFRESH_INTERVAL_SECONDS = 300.0
GDYNIA_API_UPDATE_INTERVAL_SECONDS = 300.0


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class KafkaConfig:
    """Kafka producer settings (override via environment variables)."""

    def __init__(self) -> None:
        self.enabled = _env_bool("KAFKA_ENABLED", True)
        self.bootstrap_servers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
        self.topic = os.environ.get("KAFKA_TOPIC", "port-traffic-events")
        self.client_id = os.environ.get("KAFKA_CLIENT_ID", "port-traffic-api")
        self.auto_publish_on_refresh = _env_bool("KAFKA_AUTO_PUBLISH", False)
        self.acks = os.environ.get("KAFKA_ACKS", "all")
        self.compression_type = os.environ.get("KAFKA_COMPRESSION_TYPE") or None
        self.security_protocol = os.environ.get("KAFKA_SECURITY_PROTOCOL")
        self.sasl_mechanism = os.environ.get("KAFKA_SASL_MECHANISM")
        self.sasl_username = os.environ.get("KAFKA_SASL_USERNAME")
        self.sasl_password = os.environ.get("KAFKA_SASL_PASSWORD")

    def producer_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "bootstrap_servers": self.bootstrap_servers,
            "client_id": self.client_id,
            "acks": self.acks,
            "value_serializer": lambda value: json.dumps(value, ensure_ascii=False).encode("utf-8"),
            "key_serializer": lambda key: key.encode("utf-8") if key else None,
        }
        if self.compression_type:
            kwargs["compression_type"] = self.compression_type
        if self.security_protocol:
            kwargs["security_protocol"] = self.security_protocol
        if self.sasl_mechanism:
            kwargs["sasl_mechanism"] = self.sasl_mechanism
        if self.sasl_username and self.sasl_password:
            kwargs["sasl_plain_username"] = self.sasl_username
            kwargs["sasl_plain_password"] = self.sasl_password
        return kwargs

    def status(self, *, connected: bool, last_published: int | None = None) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "connected": connected,
            "bootstrap_servers": self.bootstrap_servers,
            "topic": self.topic,
            "client_id": self.client_id,
            "auto_publish_on_refresh": self.auto_publish_on_refresh,
            "last_published_count": last_published,
        }


kafka_config = KafkaConfig()
kafka_producer: AIOKafkaProducer | None = None
kafka_last_published_count: int | None = None
cache_refresh_task: asyncio.Task[None] | None = None
gdynia_watch_task: asyncio.Task[None] | None = None
port_data_refresh_task: asyncio.Task[None] | None = None


class TrafficCache:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
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

            events = await collect_port_traffic()
            if incoming_fingerprint is None:
                incoming_fingerprint = gdynia_fingerprint_from_events(events)

            global _previous_tomtom_present
            _previous_tomtom_present = traffic_history.seen_tomtom_present_ids()
            traffic_history.record_snapshot(events)

            primary_events, context_events = split_engine_event_sources(events)
            snapshots = build_corridor_snapshots(
                primary_events,
                context_events,
                port_demand_baseline,
            )
            observation_store.append_batch(snapshots)
            engine_events = anomaly_engine.evaluate(snapshots)

            async with self._lock:
                self.events = events
                self.corridor_snapshots = snapshots
                self.engine_events = engine_events
                self.updated_at = datetime.now(timezone.utc)

            self.gdynia_changed_on_last_refresh = gdynia_changed
            self.gdynia_fingerprint = incoming_fingerprint

            if is_startup:
                self.gdynia_timer_recalibrated_at = datetime.now(timezone.utc)
                logger.info(
                    "Initial cache refresh on startup (%s events, %s engine events, Gdynia timer calibrated)",
                    len(events),
                    len(engine_events),
                )
            elif gdynia_changed:
                self.gdynia_timer_recalibrated_at = datetime.now(timezone.utc)
                logger.info(
                    "Gdynia API data changed; cache refreshed and 5min timer recalibrated (%s events, %s engine)",
                    len(events),
                    len(engine_events),
                )
            else:
                logger.info(
                    "Traffic cache refreshed (%s events, %s engine events), Gdynia data unchanged",
                    len(events),
                    len(engine_events),
                )

            if kafka_config.enabled and kafka_config.auto_publish_on_refresh:
                await publish_events_to_kafka(events)
                await publish_engine_events_to_kafka(engine_events)

            return gdynia_changed

    async def get_snapshot(self) -> tuple[list[dict[str, Any]], datetime | None]:
        async with self._lock:
            return list(self.events), self.updated_at

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
traffic_history = TrafficHistory()
observation_store = ObservationStore()
anomaly_engine = AnomalyEngine(observation_store)
port_demand_baseline = load_baseline()
_previous_tomtom_present: set[str] = set()


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
    while True:
        await asyncio.sleep(PORT_DATA_REFRESH_INTERVAL_SECONDS)
        try:
            port_data_store.refresh()
        except Exception as exc:
            logger.warning("Port data refresh failed: %s", exc)


@asynccontextmanager
async def lifespan(_: FastAPI):
    global kafka_producer, cache_refresh_task, gdynia_watch_task, port_data_refresh_task
    if kafka_config.enabled:
        producer = AIOKafkaProducer(**kafka_config.producer_kwargs())
        try:
            await producer.start()
            kafka_producer = producer
            logger.info(
                "Kafka producer connected to %s (topic=%s, client_id=%s)",
                kafka_config.bootstrap_servers,
                kafka_config.topic,
                kafka_config.client_id,
            )
        except Exception as exc:
            kafka_producer = None
            logger.warning(
                "Kafka producer unavailable (%s): %s",
                kafka_config.bootstrap_servers,
                exc,
            )
    else:
        logger.info("Kafka publishing disabled (KAFKA_ENABLED=false)")

    try:
        port_data_store.refresh()
    except Exception as exc:
        logger.warning("Initial port data load failed: %s", exc)

    try:
        await traffic_cache.refresh(is_startup=True)
    except Exception as exc:
        logger.warning("Initial cache refresh on startup failed: %s", exc)

    cache_refresh_task = asyncio.create_task(cache_refresh_loop())
    gdynia_watch_task = asyncio.create_task(gdynia_watch_loop())
    port_data_refresh_task = asyncio.create_task(port_data_refresh_loop())
    try:
        yield
    finally:
        for task_name, task in (
            ("cache_refresh_task", cache_refresh_task),
            ("gdynia_watch_task", gdynia_watch_task),
            ("port_data_refresh_task", port_data_refresh_task),
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
        if kafka_producer is not None:
            await kafka_producer.stop()
            kafka_producer = None


app = FastAPI(title="Port Traffic API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
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


def segment_centroid(geometry: dict[str, Any]) -> tuple[float, float] | None:
    coordinates = geometry.get("coordinates") or []
    if not coordinates:
        return None
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
        if geometry is None:
            continue
        centroid = segment_centroid(raw_geometry) or segment_centroid(geometry)
        if centroid is None:
            continue
        lat, lon = centroid
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
                "status": traffic_status(item["speed_kmh"]),
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


async def collect_ztm_traffic(client: httpx.AsyncClient) -> list[dict[str, Any]]:
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

    ztm_events: list[dict[str, Any]] = []
    ztm_events.extend(build_gdynia_events(intensities, segments))
    ztm_events.extend(build_szczecin_events(szczecin_raw))
    ztm_events.extend(build_gdansk_events(gdansk_raw))
    return ztm_events


async def collect_port_traffic() -> list[dict[str, Any]]:
    async with httpx.AsyncClient(follow_redirects=True) as client:
        ztm_task = collect_ztm_traffic(client)
        api_key = get_tomtom_api_key()
        if api_key:
            ztm_events, tomtom_events = await asyncio.gather(
                ztm_task,
                collect_tomtom_events(client, api_key),
            )
        else:
            if not os.environ.get("TOMTOM_API_KEY"):
                logger.info("TOMTOM_API_KEY not set — running ZTM sources only")
            ztm_events = await ztm_task
            tomtom_events = []

    segment_trends = collect_segment_trends(traffic_history)
    port_events = build_port_map_events(port_data_store)
    return fuse_traffic_events(ztm_events, tomtom_events, segment_trends, port_events)


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


def build_tomtom_source_metadata(events: list[dict[str, Any]]) -> dict[str, Any]:
    tomtom_events = [e for e in events if e.get("source_type") == "tomtom_traffic"]
    present = [e for e in tomtom_events if (e.get("context") or {}).get("time_validity") == "present"]
    future = [e for e in tomtom_events if (e.get("context") or {}).get("time_validity") == "future"]
    high_confidence = [
        e for e in present if (e.get("context") or {}).get("corroboration", {}).get("confidence") == "high"
    ]
    return {
        "record_kind": "traffic_incident",
        "event_count": len(tomtom_events),
        "present_count": len(present),
        "future_count": len(future),
        "high_confidence_count": len(high_confidence),
        "enabled": get_tomtom_api_key() is not None,
    }


def build_swinoujscie_source_metadata(events: list[dict[str, Any]]) -> dict[str, Any]:
    swi_events = [e for e in events if e.get("city") == "Swinoujscie"]
    tomtom = [e for e in swi_events if e.get("source_type") == "tomtom_traffic"]
    port_proxy = [
        e
        for e in swi_events
        if e.get("source_type") == "port_pcs"
        or (e.get("context") or {}).get("port_ops", {}).get("plszz_related")
    ]
    return {
        "record_kind": "mixed",
        "event_count": len(swi_events),
        "tomtom_incident_count": len(tomtom),
        "port_proxy_count": len(port_proxy),
        "data_quality": "tomtom_and_port_proxy",
        "note_pl": (
            "Brak publicznego API ZTM/pętli dla Świnoujścia — "
            "dane drogowe z TomTom, operacje portowe z proxy PLSZZ (Codeco)."
        ),
    }


def build_port_pcs_metadata() -> dict[str, Any]:
    summary = build_port_summary(port_data_store)
    return {
        "record_kind": "port_operations",
        "source": "pcs_excel",
        **summary,
    }


async def get_port_operations_payload() -> dict[str, Any]:
    port_events = build_port_map_events(port_data_store)
    return {
        "summary": build_port_summary(port_data_store),
        "port_calls": [e for e in port_events if e.get("record_kind") == "port_call"],
        "container_activity": [
            e for e in port_events if e.get("record_kind") == "container_activity"
        ],
    }


async def get_cached_events() -> list[dict[str, Any]]:
    events, _ = await traffic_cache.get_snapshot()
    if not events:
        await traffic_cache.refresh(is_startup=True)
        events, _ = await traffic_cache.get_snapshot()
    return events


def intelligence_snapshot(events: list[dict[str, Any]]) -> dict[str, Any]:
    anomalies = detect_anomalies(
        events,
        traffic_history,
        previous_tomtom_present=_previous_tomtom_present,
    )
    predictions = build_predictions(events, traffic_history)
    report = build_operational_report(events, traffic_history, anomalies=anomalies, predictions=predictions)
    hourly_report = build_hourly_incidents_report(events, traffic_history, window_minutes=60)
    return {
        "anomalies": anomalies,
        "predictions": predictions,
        "report": report,
        "hourly_report": hourly_report,
        "bottlenecks": traffic_history.rank_bottlenecks(window_minutes=60, limit=10),
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


def split_engine_event_sources(
    events: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    primary = [event for event in events if event.get("source_type") == "tomtom_traffic"]
    context = [event for event in events if event.get("source_type") != "tomtom_traffic"]
    return primary, context


def engine_event_to_kafka(engine_event: dict[str, Any]) -> dict[str, Any]:
    city_map = {
        "Port Gdańsk": "Gdansk",
        "Port Gdynia": "Gdynia",
        "Port Szczecin": "Szczecin",
        "Port Świnoujście": "Swinoujscie",
    }
    port_name = engine_event.get("port") or ""
    severity = int(engine_event.get("severity") or 0)
    status = "CRITICAL" if severity >= 75 else "CONGESTION" if severity >= 45 else "CLEAR"
    return {
        "event_id": f"port_anomaly_{engine_event.get('id')}",
        "record_kind": "port_anomaly",
        "entity_id": engine_event.get("corridor_id"),
        "city": city_map.get(port_name, "Trojmiasto"),
        "source_type": "port_anomaly_engine",
        "timestamp": engine_event.get("timestamp") or datetime.now(timezone.utc).isoformat(),
        "location": {
            "road_name": engine_event.get("roadSegment"),
            "lat": None,
            "lon": None,
        },
        "geometry": None,
        "metrics": {
            "severity": severity,
            "confidence": engine_event.get("confidence"),
            "event_type": engine_event.get("eventType"),
        },
        "status": status,
        "context": {
            "dispatch_impact": engine_event.get("dispatch_impact"),
            "port_context": engine_event.get("port_context"),
            "summary_pl": engine_event.get("summary"),
            "engine": engine_event,
        },
    }


async def publish_engine_events_to_kafka(engine_events: list[dict[str, Any]]) -> int:
    if not engine_events:
        return 0
    kafka_events = [engine_event_to_kafka(item) for item in engine_events]
    return await publish_events_to_kafka(kafka_events)


async def publish_events_to_kafka(events: list[dict[str, Any]]) -> int:
    global kafka_last_published_count
    if not kafka_config.enabled:
        logger.info("Skipping Kafka publish: KAFKA_ENABLED=false")
        return 0
    if kafka_producer is None:
        logger.warning("Skipping Kafka publish: producer is not connected")
        return 0

    published = 0
    for event in events:
        try:
            await kafka_producer.send_and_wait(
                kafka_config.topic,
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
    kafka_last_published_count = published
    logger.info(
        "Published %s/%s events to topic %s",
        published,
        len(events),
        kafka_config.topic,
    )
    return published


@app.get("/api/v1/port-traffic")
async def get_port_traffic(
    publish_kafka: bool = Query(
        default=None,
        description="Publish events to Kafka (defaults to KAFKA_AUTO_PUBLISH or true for live fetch)",
    ),
    use_cache: bool = Query(default=False, description="Return cached data instead of live fetch"),
) -> list[dict[str, Any]] | dict[str, Any]:
    if use_cache:
        return await get_map_data()

    events = await collect_port_traffic()
    should_publish = publish_kafka if publish_kafka is not None else True
    if should_publish:
        await publish_events_to_kafka(events)
    return events


@app.get("/api/v1/map-data")
async def get_map_data() -> dict[str, Any]:
    events = await get_cached_events()
    _, updated_at = await traffic_cache.get_snapshot()
    snapshots, engine_events, engine_updated_at = await traffic_cache.get_engine_state()
    intel = intelligence_snapshot(events)
    port_events = build_port_map_events(port_data_store)
    road_events = [e for e in events if e.get("record_kind") not in ("port_call", "container_activity", "codeco_move")]
    primary_events, context_events = split_engine_event_sources(events)

    return {
        "events": road_events,
        "port_events": port_events,
        "port_summary": build_port_summary(port_data_store, traffic_events=road_events),
        "terminals_catalog": build_terminals_catalog(port_data_store),
        "approach_zones": build_approach_zones(port_data_store, traffic_events=road_events),
        "city_port_dashboard": build_city_port_dashboard(port_data_store, traffic_events=road_events),
        "codeco_hourly_24h": build_codeco_hourly_24h(port_data_store),
        "engine_events": engine_events,
        "corridor_snapshots": snapshots,
        "engine_bottlenecks": anomaly_engine.bottlenecks_last_hour(),
        "port_demand_analysis": analyze_cities(port_demand_baseline, primary_events, context_events),
        "engine_corridor_config": load_corridor_config(),
        "cached_at": updated_at.isoformat() if updated_at else None,
        "engine_evaluated_at": engine_updated_at.isoformat() if engine_updated_at else None,
        "observation_count": observation_store.corridor_count(),
        "age_seconds": traffic_cache.age_seconds(),
        "refresh_interval_seconds": CACHE_REFRESH_INTERVAL_SECONDS,
        "bottlenecks": intel["bottlenecks"],
        "operational_report": intel["report"],
        "hourly_report": intel["hourly_report"],
        "sources": {
            "gdynia": enrich_gdynia_metadata(events),
            "szczecin": build_city_source_metadata(events, "Szczecin", "vehicle"),
            "gdansk": build_city_source_metadata(events, "Gdansk", "vehicle"),
            "swinoujscie": build_swinoujscie_source_metadata(events),
            "tomtom": build_tomtom_source_metadata(events),
            "port_pcs": build_port_pcs_metadata(),
        },
        "kafka": kafka_config.status(
            connected=kafka_producer is not None,
            last_published=kafka_last_published_count,
        ),
    }


@app.get("/api/v1/port-operations")
async def get_port_operations() -> dict[str, Any]:
    return await get_port_operations_payload()


@app.get("/api/v1/hourly-report")
async def get_hourly_report(
    window_minutes: int = Query(default=60, ge=15, le=240),
) -> dict[str, Any]:
    events = await get_cached_events()
    return build_hourly_incidents_report(events, traffic_history, window_minutes=window_minutes)


@app.get("/api/v1/bottlenecks")
async def get_bottlenecks(
    window_minutes: int = Query(default=60, ge=5, le=120),
    limit: int = Query(default=10, ge=1, le=50),
) -> dict[str, Any]:
    events = await get_cached_events()
    return {
        "window_minutes": window_minutes,
        "bottlenecks": traffic_history.rank_bottlenecks(window_minutes=window_minutes, limit=limit),
        "event_count": len(events),
    }


@app.get("/api/v1/anomalies")
async def get_anomalies() -> dict[str, Any]:
    events = await get_cached_events()
    anomalies = detect_anomalies(
        events,
        traffic_history,
        previous_tomtom_present=_previous_tomtom_present,
    )
    return {"anomalies": anomalies, "count": len(anomalies)}


@app.get("/api/v1/predictions")
async def get_predictions(
    horizon_minutes: int = Query(default=60, ge=15, le=240),
) -> dict[str, Any]:
    events = await get_cached_events()
    predictions = build_predictions(events, traffic_history, horizon_minutes=horizon_minutes)
    return {"horizon_minutes": horizon_minutes, "predictions": predictions, "count": len(predictions)}


@app.get("/api/v1/operational-report")
async def get_operational_report() -> dict[str, Any]:
    events = await get_cached_events()
    intel = intelligence_snapshot(events)
    return intel["report"]


@app.get("/api/v1/engine/events")
async def get_engine_events() -> dict[str, Any]:
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
    _, _, updated_at = await traffic_cache.get_engine_state()
    if updated_at is None:
        await traffic_cache.refresh(is_startup=True)
        _, _, updated_at = await traffic_cache.get_engine_state()
    return {
        "window_minutes": window,
        "evaluated_at": updated_at.isoformat() if updated_at else None,
        "bottlenecks": anomaly_engine.bottlenecks_last_hour(),
    }


@app.get("/api/v1/engine/corridors")
async def get_engine_corridors() -> dict[str, Any]:
    snapshots, events, updated_at = await traffic_cache.get_engine_state()
    if not snapshots:
        await traffic_cache.refresh(is_startup=True)
        snapshots, events, updated_at = await traffic_cache.get_engine_state()
    return {
        "evaluated_at": updated_at.isoformat() if updated_at else None,
        "corridors": snapshots,
        "related_events": events,
    }


@app.get("/api/v1/engine/corridor-config")
async def get_engine_corridor_config() -> dict[str, Any]:
    return load_corridor_config()


@app.get("/api/v1/routing/forecast")
async def get_routing_forecast() -> dict[str, Any]:
    return await build_route_forecast()


@app.get("/api/v1/routing/status")
async def get_routing_status() -> dict[str, Any]:
    return {
        "routing_enabled": routing_enabled(),
        "tomtom_api_configured": bool(get_tomtom_api_key()),
    }


@app.get("/api/v1/routing/bypasses")
async def get_routing_bypasses(
    incident_id: str = "",
    lat: float | None = None,
    lon: float | None = None,
) -> dict[str, Any]:
    if lat is None or lon is None:
        return {
            "enabled": routing_enabled(),
            "recommended": False,
            "error": "lat and lon query parameters are required",
            "incident_id": incident_id or None,
        }
    result = await compute_bypass(lat=lat, lon=lon)
    if incident_id:
        result["incident_id"] = incident_id
    return result


@app.get("/")
async def map_page() -> FileResponse:
    return FileResponse("map.html")


@app.get("/map")
async def map_page_alias() -> FileResponse:
    return FileResponse("map.html")


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "kafka": kafka_config.status(
            connected=kafka_producer is not None,
            last_published=kafka_last_published_count,
        ),
    }


@app.get("/api/v1/kafka/status")
async def kafka_status() -> dict[str, Any]:
    return kafka_config.status(
        connected=kafka_producer is not None,
        last_published=kafka_last_published_count,
    )
