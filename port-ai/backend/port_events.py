"""Build map events from PCS port operational data."""

from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

import json
from pathlib import Path

from port_data_loader import PortDataStore, _parse_dt

APPROACH_ZONES_PATH = Path(__file__).resolve().parent / "data" / "port" / "approach_zones.json"


CODECO_TERMINALS: tuple[str, ...] = ("DCT", "GCT", "BCT", "DBPS")
PORT_AGGREGATE_NODES: tuple[str, ...] = ("PLSZZ",)
CHART_TERMINALS: tuple[str, ...] = (*CODECO_TERMINALS, "PLSZZ")

CITY_PORT_GROUPS: tuple[dict[str, Any], ...] = (
    {"key": "gdansk", "label": "Gdańsk", "cities": ("Gdansk",)},
    {"key": "gdynia", "label": "Gdynia", "cities": ("Gdynia",)},
    {"key": "szczecin", "label": "Szczecin", "cities": ("Szczecin",)},
    {"key": "swinoujscie", "label": "Świnoujście", "cities": ("Swinoujscie",)},
)

ROAD_STATUS_LABELS_PL: dict[str, str] = {
    "CLEAR": "Płynnie",
    "CONGESTION": "Zagęszczenie",
    "CRITICAL": "Korek",
    "unknown": "Brak danych",
}

GENERIC_ROAD_TOKENS: frozenset[str] = frozenset(
    {"port", "trasa", "drogi", "obwodnica", "ul", "do", "na", "od", "wjazd"}
)

CITY_ALIASES: dict[str, str] = {
    "gdansk": "gdansk",
    "gdańsk": "gdansk",
    "gdynia": "gdynia",
    "szczecin": "szczecin",
    "swinoujscie": "swinoujscie",
    "świnoujście": "swinoujscie",
}


def resolve_location(
    *,
    berth_name: str | None = None,
    terminal: str | None = None,
    port_code: str | None = None,
    terminals_config: dict[str, Any],
) -> dict[str, Any]:
    berths = terminals_config.get("berths") or {}
    terminals = terminals_config.get("terminals") or {}

    if berth_name and berth_name in berths:
        entry = berths[berth_name]
        return {
            "lat": entry["lat"],
            "lon": entry["lon"],
            "road_name": berth_name,
            "city": entry.get("city", "Gdansk"),
            "terminal": entry.get("terminal"),
        }

    if berth_name:
        for key, entry in berths.items():
            if key.lower() in str(berth_name).lower() or str(berth_name).lower() in key.lower():
                return {
                    "lat": entry["lat"],
                    "lon": entry["lon"],
                    "road_name": berth_name,
                    "city": entry.get("city", "Gdansk"),
                    "terminal": entry.get("terminal"),
                }

    if terminal and terminal in terminals:
        entry = terminals[terminal]
        return {
            "lat": entry["lat"],
            "lon": entry["lon"],
            "road_name": entry.get("label", terminal),
            "city": entry.get("city", "Gdansk"),
            "terminal": terminal,
        }

    if port_code and port_code in terminals:
        entry = terminals[port_code]
        return {
            "lat": entry["lat"],
            "lon": entry["lon"],
            "road_name": entry.get("label", port_code),
            "city": entry.get("city", "Gdansk"),
            "terminal": port_code,
        }

    return {"lat": 54.40, "lon": 18.66, "road_name": berth_name or terminal or "Port", "city": "Gdansk"}


def truck_demand_hint(
    *,
    moves_last_hour: int,
    loa_m: float | None = None,
    dwt: float | None = None,
    full_moves: int = 0,
) -> str:
    if (loa_m or 0) > 200 or (dwt or 0) > 50000 or moves_last_hour > 30 or full_moves > 20:
        return "high"
    if moves_last_hour >= 10 or full_moves >= 8:
        return "medium"
    return "low"


def port_call_status_color(status: str) -> str:
    if status == "in_port":
        return "CONGESTION"
    if status == "expected":
        return "CLEAR"
    return "CLEAR"


def build_port_call_events(store: PortDataStore) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    events: list[dict[str, Any]] = []
    config = store.terminals_config

    for call in store.port_calls:
        imo = call.get("ship_imo")
        vessel = store.vessel_for_imo(imo)
        location = resolve_location(
            berth_name=call.get("berth_name"),
            port_code=call.get("port_code"),
            terminals_config=config,
        )
        loa = float(vessel["loa_m"]) if vessel and vessel.get("loa_m") else None
        dwt = float(vessel["dwt"]) if vessel and vessel.get("dwt") else None
        status = call.get("status") or "expected"
        eta = _parse_dt(call.get("eta"))
        ata = _parse_dt(call.get("ata"))

        if status == "expected" and eta and eta < now - timedelta(hours=6):
            continue
        if status == "departed":
            continue

        events.append(
            {
                "event_id": f"port_call_{call['call_id']}",
                "record_kind": "port_call",
                "entity_id": str(call.get("call_id")),
                "city": location.get("city", "Gdansk"),
                "source_type": "port_pcs",
                "timestamp": (ata or eta or now).isoformat(),
                "location": {
                    "lat": location["lat"],
                    "lon": location["lon"],
                    "road_name": location.get("road_name"),
                },
                "geometry": None,
                "metrics": {
                    "loa_m": loa,
                    "dwt": dwt,
                    "ship_name": call.get("ship_name") or (vessel or {}).get("name"),
                    "imo": imo,
                },
                "status": port_call_status_color(status),
                "context": {
                    "port_ops": {
                        "call_status": status,
                        "berth_name": call.get("berth_name"),
                        "port_name": call.get("port_name"),
                        "terminal": location.get("terminal"),
                        "eta": call.get("eta"),
                        "ata": call.get("ata"),
                        "etd": call.get("etd"),
                        "voyage_no": call.get("voyage_no"),
                        "ship_type": (vessel or {}).get("ship_type"),
                        "truck_demand_hint": truck_demand_hint(
                            moves_last_hour=0,
                            loa_m=loa,
                            dwt=dwt,
                        ),
                    }
                },
            }
        )
    return events


def _terminal_meta(terminal: str, moves: list[dict[str, Any]], terminals_config: dict[str, Any]) -> dict[str, Any]:
    meta = terminals_config.get(terminal)
    if not meta:
        for port_key in ("PLGDN", "PLGDY", "PLSZZ"):
            if port_key in terminals_config and any(
                port_key in str(move.get("load_port") or "") or port_key in str(move.get("unload_port") or "")
                for move in moves
            ):
                meta = terminals_config[port_key]
                break
    if not meta:
        meta = {"lat": 54.40, "lon": 18.66, "city": "Gdansk", "label": terminal, "corridor": "trojmiasto_port"}
    return meta


def _reference_now(store: PortDataStore) -> tuple[datetime, bool]:
    """Use latest Codeco timestamp when export is stale (static Excel, not live stream)."""
    now = datetime.now(timezone.utc)
    latest: datetime | None = None
    for move in store.container_moves:
        ts = _parse_dt(move.get("timestamp"))
        if ts is not None and (latest is None or ts > latest):
            latest = ts
    if latest is not None and (now - latest).total_seconds() > 3600:
        return latest, True
    return now, False


def _hour_bucket(ts: datetime) -> datetime:
    return ts.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


def _activity_counts(moves: list[dict[str, Any]], *, now: datetime) -> dict[str, int | bool]:
    hour_ago = now - timedelta(hours=1)
    recent_hour = [
        move
        for move in moves
        if (_parse_dt(move.get("timestamp")) or now) >= hour_ago
    ]
    hours_span = max(
        1.0,
        min(24.0, (now - min(_parse_dt(m.get("timestamp")) or now for m in moves)).total_seconds() / 3600.0),
    ) if moves else 1.0
    moves_in_last_hour = len(recent_hour)
    active_last_hour = moves_in_last_hour > 0
    estimated_per_hour = max(0, int(len(moves) / hours_span)) if moves else 0
    full_moves_hour = sum(
        1 for move in recent_hour if str(move.get("full_empty") or "").lower().startswith("peł")
    )
    full_moves = sum(1 for move in moves if str(move.get("full_empty") or "").lower().startswith("peł"))
    export_moves = sum(1 for move in moves if move.get("direction") == "export")
    import_moves = len(moves) - export_moves
    plszz_moves = sum(
        1 for move in moves if move.get("load_port") == "PLSZZ" or move.get("unload_port") == "PLSZZ"
    )
    return {
        "moves_in_last_hour": moves_in_last_hour,
        "active_last_hour": active_last_hour,
        "moves_last_hour": moves_in_last_hour if active_last_hour else estimated_per_hour,
        "full_moves_last_hour": full_moves_hour if active_last_hour else 0,
        "full_moves_24h": full_moves,
        "export_moves_24h": export_moves,
        "import_moves_24h": import_moves,
        "plszz_moves_24h": plszz_moves,
        "total_moves_24h": len(moves),
    }


def _container_activity_event(
    *,
    terminal: str,
    meta: dict[str, Any],
    counts: dict[str, int],
    now: datetime,
    city: str,
    source_label: str = "codeco",
) -> dict[str, Any]:
    count = int(counts["moves_last_hour"])
    hint = truck_demand_hint(
        moves_last_hour=count,
        full_moves=int(counts.get("full_moves_last_hour") or counts.get("full_moves_24h") or 0),
    )
    active = bool(counts.get("active_last_hour"))
    return {
        "event_id": f"codeco_activity_{terminal}_{now.strftime('%Y%m%d%H')}",
        "record_kind": "container_activity",
        "entity_id": terminal,
        "city": city,
        "source_type": "port_pcs",
        "timestamp": now.isoformat(),
        "location": {
            "lat": meta["lat"],
            "lon": meta["lon"],
            "road_name": meta.get("label", terminal),
        },
        "geometry": None,
        "metrics": {
            "moves_in_last_hour": counts["moves_in_last_hour"],
            "active_last_hour": active,
            "moves_last_hour": count,
            "full_moves_last_hour": counts["full_moves_last_hour"],
            "export_moves_24h": counts["export_moves_24h"],
            "import_moves_24h": counts["import_moves_24h"],
            "total_moves_24h": counts["total_moves_24h"],
            "activity_radius_m": min(900, 220 + count * 10) if active else 120,
        },
        "status": "CRITICAL" if hint == "high" and active else "CONGESTION" if (hint == "medium" and active) else "CLEAR",
        "context": {
            "port_ops": {
                "data_source": source_label,
                "terminal": terminal,
                "active_last_hour": active,
                "moves_in_last_hour": counts["moves_in_last_hour"],
                "moves_last_hour": count,
                "full_moves_last_hour": counts["full_moves_last_hour"],
                "export_moves_24h": counts["export_moves_24h"],
                "import_moves_24h": counts["import_moves_24h"],
                "plszz_moves_24h": counts["plszz_moves_24h"],
                "truck_demand_hint": hint,
                "corridor": meta.get("corridor", "trojmiasto_port"),
                "plszz_related": counts["plszz_moves_24h"] > 0,
            }
        },
    }


def build_codeco_hourly_24h(store: PortDataStore) -> dict[str, Any]:
    """Hourly Codeco move counts per terminal for the trailing 24 h window."""
    reference, data_anchored = _reference_now(store)
    window_start = reference - timedelta(hours=23)
    bucket_keys = [_hour_bucket(window_start + timedelta(hours=offset)) for offset in range(24)]
    totals: dict[str, dict[datetime, int]] = {terminal: defaultdict(int) for terminal in CHART_TERMINALS}

    for move in store.container_moves:
        ts = _parse_dt(move.get("timestamp"))
        if ts is None:
            continue
        bucket = _hour_bucket(ts)
        if bucket < bucket_keys[0] or bucket > bucket_keys[-1]:
            continue
        terminal = str(move.get("terminal") or "UNKNOWN")
        if terminal in totals:
            totals[terminal][bucket] += 1
        if move.get("load_port") == "PLSZZ" or move.get("unload_port") == "PLSZZ":
            totals["PLSZZ"][bucket] += 1

    buckets: list[dict[str, Any]] = []
    for bucket in bucket_keys:
        per_terminal = {terminal: int(totals[terminal].get(bucket, 0)) for terminal in CHART_TERMINALS}
        buckets.append(
            {
                "hour": bucket.isoformat(),
                "label": bucket.strftime("%H:%M"),
                "totals": per_terminal,
                "total": sum(per_terminal.values()),
            }
        )

    return {
        "reference_time": reference.isoformat(),
        "data_anchored": data_anchored,
        "terminals": list(CHART_TERMINALS),
        "buckets": buckets,
        "peak_hour": max(buckets, key=lambda item: item["total"], default=None),
    }


def build_container_activity_events(store: PortDataStore) -> list[dict[str, Any]]:
    now, _ = _reference_now(store)
    lookback = now - timedelta(hours=24)
    terminals_config = store.terminals_config.get("terminals") or {}

    by_terminal: dict[str, list[dict[str, Any]]] = {t: [] for t in CODECO_TERMINALS}
    plszz_moves: list[dict[str, Any]] = []

    for move in store.container_moves:
        ts = _parse_dt(move.get("timestamp"))
        if ts is None or ts < lookback:
            continue
        terminal = str(move.get("terminal") or "UNKNOWN")
        if terminal not in by_terminal:
            by_terminal[terminal] = []
        by_terminal[terminal].append(move)
        if move.get("load_port") == "PLSZZ" or move.get("unload_port") == "PLSZZ":
            plszz_moves.append(move)

    events: list[dict[str, Any]] = []
    for terminal in CODECO_TERMINALS:
        moves = by_terminal.get(terminal, [])
        meta = _terminal_meta(terminal, moves, terminals_config)
        counts = _activity_counts(moves, now=now)
        city = meta.get("city", "Gdansk")
        events.append(
            _container_activity_event(
                terminal=terminal,
                meta=meta,
                counts=counts,
                now=now,
                city=city,
            )
        )

    for terminal, moves in by_terminal.items():
        if terminal in CODECO_TERMINALS or not moves:
            continue
        meta = _terminal_meta(terminal, moves, terminals_config)
        counts = _activity_counts(moves, now=now)
        events.append(
            _container_activity_event(
                terminal=terminal,
                meta=meta,
                counts=counts,
                now=now,
                city=meta.get("city", "Gdansk"),
            )
        )

    plszz_meta = terminals_config.get("PLSZZ", {})
    plszz_counts = _activity_counts(plszz_moves, now=now)
    events.append(
        _container_activity_event(
            terminal="PLSZZ",
            meta=plszz_meta,
            counts=plszz_counts,
            now=now,
            city="Swinoujscie",
            source_label="codeco_plszz",
        )
    )

    return events


def build_recent_codeco_move_events(store: PortDataStore, *, limit: int = 80) -> list[dict[str, Any]]:
    """Recent individual Codeco moves for map visualization."""
    now = datetime.now(timezone.utc)
    lookback = now - timedelta(hours=24)
    terminals_config = store.terminals_config.get("terminals") or {}

    candidates: list[tuple[datetime, dict[str, Any]]] = []
    for move in store.container_moves:
        ts = _parse_dt(move.get("timestamp"))
        if ts is None or ts < lookback:
            continue
        candidates.append((ts, move))

    candidates.sort(key=lambda item: item[0], reverse=True)
    events: list[dict[str, Any]] = []

    for ts, move in candidates[:limit]:
        terminal = str(move.get("terminal") or "UNKNOWN")
        moves_for_terminal = [move]
        meta = _terminal_meta(terminal, moves_for_terminal, terminals_config)
        if move.get("load_port") == "PLSZZ" or move.get("unload_port") == "PLSZZ":
            meta = terminals_config.get("PLSZZ", meta)
        direction = move.get("direction") or "import"
        is_full = str(move.get("full_empty") or "").lower().startswith("peł")
        city = "Swinoujscie" if (move.get("load_port") == "PLSZZ" or move.get("unload_port") == "PLSZZ") else meta.get("city", "Gdansk")

        events.append(
            {
                "event_id": f"codeco_move_{move.get('move_id')}",
                "record_kind": "codeco_move",
                "entity_id": str(move.get("move_id")),
                "city": city,
                "source_type": "port_pcs",
                "timestamp": ts.isoformat(),
                "location": {
                    "lat": meta["lat"],
                    "lon": meta["lon"],
                    "road_name": meta.get("label", terminal),
                },
                "geometry": None,
                "metrics": {
                    "terminal": terminal,
                    "full_empty": move.get("full_empty"),
                    "load_port": move.get("load_port"),
                    "unload_port": move.get("unload_port"),
                    "direction": direction,
                    "is_full": is_full,
                },
                "status": "CONGESTION" if is_full else "CLEAR",
                "context": {
                    "port_ops": {
                        "data_source": "codeco",
                        "terminal": terminal,
                        "direction": direction,
                        "status_code": move.get("status_code"),
                    }
                },
            }
        )

    return events


def load_approach_zones_config() -> dict[str, Any]:
    if APPROACH_ZONES_PATH.is_file():
        with APPROACH_ZONES_PATH.open(encoding="utf-8") as handle:
            return json.load(handle)
    return {"zones": []}


def _normalize_city(city: str | None) -> str | None:
    if not city:
        return None
    normalized = city.strip().lower()
    return CITY_ALIASES.get(normalized, normalized)


def _cities_match(left: str | None, right: str | None) -> bool:
    left_norm = _normalize_city(left)
    right_norm = _normalize_city(right)
    if not left_norm or not right_norm:
        return True
    return left_norm == right_norm


def _road_match_tokens(road_pl: str) -> list[str]:
    normalized = road_pl.lower()
    normalized = re.sub(r"\bul\.\s*", "", normalized)
    normalized = re.sub(r"\bdk\s*", "dk", normalized)
    tokens = re.findall(r"[a-z0-9ąćęłńóśźż]+", normalized)
    return [token for token in tokens if len(token) >= 2]


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius_km * math.asin(math.sqrt(a))


def _geometry_coords_lonlat(geometry: dict[str, Any] | None) -> list[list[float]]:
    if not geometry:
        return []
    geom_type = geometry.get("type")
    raw = geometry.get("coordinates") or []
    if geom_type == "LineString":
        return [[float(p[0]), float(p[1])] for p in raw if isinstance(p, (list, tuple)) and len(p) >= 2]
    if geom_type == "MultiLineString":
        coords: list[list[float]] = []
        for line in raw:
            coords.extend(
                [[float(p[0]), float(p[1])] for p in line if isinstance(p, (list, tuple)) and len(p) >= 2]
            )
        return coords
    if geom_type == "Point" and len(raw) >= 2:
        return [[float(raw[0]), float(raw[1])]]
    return []


def _min_distance_coords_km(a_coords: list[list[float]], b_coords: list[list[float]]) -> float:
    if not a_coords or not b_coords:
        return float("inf")
    return min(
        _haversine_km(a[1], a[0], b[1], b[0])
        for a in a_coords
        for b in b_coords
    )


def _line_buffer_polygon(coords_lonlat: list[list[float]], half_width_deg: float = 0.0016) -> dict[str, Any] | None:
    """Rough corridor polygon around a polyline (~140 m at Baltic latitudes)."""
    if len(coords_lonlat) < 2:
        return None
    left: list[list[float]] = []
    right: list[list[float]] = []
    count = len(coords_lonlat)

    def normal_at(index: int) -> tuple[float, float]:
        if index == 0:
            dx = coords_lonlat[1][0] - coords_lonlat[0][0]
            dy = coords_lonlat[1][1] - coords_lonlat[0][1]
        elif index == count - 1:
            dx = coords_lonlat[-1][0] - coords_lonlat[-2][0]
            dy = coords_lonlat[-1][1] - coords_lonlat[-2][1]
        else:
            dx = coords_lonlat[index + 1][0] - coords_lonlat[index - 1][0]
            dy = coords_lonlat[index + 1][1] - coords_lonlat[index - 1][1]
        length = math.hypot(dx, dy) or 1e-12
        return -dy / length, dx / length

    for index, (lon, lat) in enumerate(coords_lonlat):
        nx, ny = normal_at(index)
        left.append([lon + nx * half_width_deg, lat + ny * half_width_deg])
        right.append([lon - nx * half_width_deg, lat - ny * half_width_deg])

    ring = left + list(reversed(right))
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    return {"type": "Polygon", "coordinates": [ring]}


def _token_matches_haystack(token: str, haystack: str) -> bool:
    if re.fullmatch(r"s\d+", token):
        return bool(re.search(rf"\b{re.escape(token)}\b", haystack))
    if re.fullmatch(r"dk\d+", token):
        return bool(re.search(rf"\b{re.escape(token)}\b", haystack))
    if len(token) < 4:
        return False
    return token in haystack


def road_matches_traffic_event(
    road_pl: str,
    event: dict[str, Any],
    *,
    city: str | None = None,
) -> bool:
    if city and not _cities_match(event.get("city"), city):
        return False

    location = event.get("location") or {}
    haystack = " ".join(
        str(part or "")
        for part in (
            location.get("road_name"),
            event.get("entity_id"),
            (event.get("context") or {}).get("driver_summary_pl"),
            (event.get("context") or {}).get("tomtom_road"),
        )
    ).lower()
    if not haystack.strip():
        return False

    tokens = _road_match_tokens(road_pl)
    significant = [token for token in tokens if token not in GENERIC_ROAD_TOKENS]
    if not significant:
        significant = tokens

    matched = [token for token in significant if _token_matches_haystack(token, haystack)]
    if not matched:
        return False
    if len(significant) >= 2 and len(matched) < 2:
        return False
    return True


def _event_operational_status(event: dict[str, Any]) -> str:
    """Downgrade noisy matches (e.g. zero-delay incidents) for TIR road KPIs."""
    base = str(event.get("status") or "CLEAR")
    if base not in {"CRITICAL", "CONGESTION"}:
        return base

    metrics = event.get("metrics") or {}
    context = event.get("context") or {}
    delay = int(metrics.get("delay_sec") or metrics.get("total_delay_sec") or context.get("delay_sec") or 0)
    record_kind = str(event.get("record_kind") or "")

    if record_kind == "incident" and delay < 30:
        icon = str(context.get("icon_category") or "").lower()
        if icon not in {"closed", "roadclosed", "road_closed"}:
            return "CONGESTION" if base == "CRITICAL" else base

    if record_kind == "vehicle" and delay == 0 and base == "CRITICAL":
        speed = metrics.get("speed_kmh")
        if speed is not None and float(speed) > 8:
            return "CONGESTION"

    return base


def _collect_snapped_geometries(
    zone: dict[str, Any],
    traffic_events: list[dict[str, Any]],
    *,
    max_distance_km: float = 0.45,
) -> list[dict[str, Any]]:
    """Match TomTom/Gdynia LineStrings lying near the reference TIR corridor."""
    reference_coords = _geometry_coords_lonlat(zone.get("geometry"))
    if not reference_coords:
        return []
    roads = zone.get("roads_pl") or []
    snapped: list[dict[str, Any]] = []
    seen: set[str] = set()

    for event in traffic_events:
        geometry = event.get("geometry")
        if not geometry or geometry.get("type") != "LineString":
            continue
        event_coords = _geometry_coords_lonlat(geometry)
        if not event_coords:
            continue
        if _min_distance_coords_km(reference_coords, event_coords) > max_distance_km:
            continue
        name_match = any(
            road_matches_traffic_event(road, event, city=zone.get("city"))
            for road in roads
        )
        record_kind = event.get("record_kind")
        if not name_match and record_kind not in ("road_segment", "traffic_incident"):
            continue
        key = json.dumps(geometry.get("coordinates"), sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        snapped.append(geometry)
    return snapped


def _merge_line_geometries(geometries: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not geometries:
        return None
    if len(geometries) == 1:
        return geometries[0]
    lines = [geom.get("coordinates") for geom in geometries if geom.get("coordinates")]
    if not lines:
        return None
    return {"type": "MultiLineString", "coordinates": lines}


def _enrich_corridor_geometry(
    zone: dict[str, Any],
    traffic_events: list[dict[str, Any]],
) -> dict[str, Any]:
    reference = zone.get("geometry")
    snapped = _collect_snapped_geometries(zone, traffic_events)
    display_geometry = _merge_line_geometries(snapped) or reference
    display_coords = _geometry_coords_lonlat(display_geometry)
    corridor_band = _line_buffer_polygon(display_coords) if display_coords else None
    return {
        "geometry": display_geometry,
        "reference_geometry": reference,
        "corridor_band": corridor_band,
        "geometry_source": "snapped" if snapped else "reference",
        "snapped_segments": len(snapped),
    }


def resolve_road_traffic_status(
    road_pl: str,
    traffic_events: list[dict[str, Any]],
    *,
    city: str | None = None,
) -> dict[str, Any]:
    matches = [
        event
        for event in traffic_events
        if road_matches_traffic_event(road_pl, event, city=city)
    ]
    if not matches:
        return {
            "road": road_pl,
            "status": "unknown",
            "label_pl": ROAD_STATUS_LABELS_PL["unknown"],
            "matched_events": 0,
        }
    statuses = [_event_operational_status(event) for event in matches]
    if "CRITICAL" in statuses:
        status = "CRITICAL"
    elif "CONGESTION" in statuses:
        status = "CONGESTION"
    else:
        status = "CLEAR"
    return {
        "road": road_pl,
        "status": status,
        "label_pl": ROAD_STATUS_LABELS_PL[status],
        "matched_events": len(matches),
    }


def _worst_road_status(statuses: list[str]) -> str:
    if "CRITICAL" in statuses:
        return "CRITICAL"
    if "CONGESTION" in statuses:
        return "CONGESTION"
    if any(status != "unknown" for status in statuses):
        return "CLEAR"
    return "unknown"


def build_terminals_catalog(store: PortDataStore) -> list[dict[str, Any]]:
    """All Codeco terminals with data + activity in the last hour."""
    now, data_anchored = _reference_now(store)
    lookback = now - timedelta(hours=24)
    terminals_config = store.terminals_config.get("terminals") or {}

    by_terminal: dict[str, list[dict[str, Any]]] = {t: [] for t in CODECO_TERMINALS}
    plszz_moves: list[dict[str, Any]] = []
    all_time_terminals: set[str] = set()

    for move in store.container_moves:
        terminal = str(move.get("terminal") or "UNKNOWN")
        all_time_terminals.add(terminal)
        ts = _parse_dt(move.get("timestamp"))
        if ts is None or ts < lookback:
            continue
        if terminal not in by_terminal:
            by_terminal[terminal] = []
        by_terminal[terminal].append(move)
        if move.get("load_port") == "PLSZZ" or move.get("unload_port") == "PLSZZ":
            plszz_moves.append(move)

    catalog: list[dict[str, Any]] = []

    def append_entry(terminal: str, moves: list[dict[str, Any]], *, city: str, label: str | None = None) -> None:
        meta = terminals_config.get(terminal) or _terminal_meta(terminal, moves, terminals_config)
        counts = _activity_counts(moves, now=now)
        hint = truck_demand_hint(
            moves_last_hour=int(counts["moves_last_hour"]),
            full_moves=int(counts.get("full_moves_24h") or 0),
        )
        catalog.append(
            {
                "terminal": terminal,
                "label": label or meta.get("label", terminal),
                "description_pl": meta.get("description_pl"),
                "city": city,
                "lat": meta.get("lat"),
                "lon": meta.get("lon"),
                "has_codeco_data": terminal in all_time_terminals or terminal == "PLSZZ",
                "active_last_hour": bool(counts["active_last_hour"]),
                "moves_in_last_hour": int(counts["moves_in_last_hour"]),
                "moves_last_hour_display": int(counts["moves_last_hour"]),
                "total_moves_24h": int(counts["total_moves_24h"]),
                "export_moves_24h": int(counts["export_moves_24h"]),
                "import_moves_24h": int(counts["import_moves_24h"]),
                "truck_demand_hint": hint if counts["active_last_hour"] else "idle",
                "corridor": meta.get("corridor"),
                "data_anchored": data_anchored,
            }
        )

    for terminal in CODECO_TERMINALS:
        meta = terminals_config.get(terminal, {})
        append_entry(
            terminal,
            by_terminal.get(terminal, []),
            city=meta.get("city", "Gdansk"),
            label=meta.get("label"),
        )

    for terminal in sorted(all_time_terminals):
        if terminal in CODECO_TERMINALS:
            continue
        meta = _terminal_meta(terminal, by_terminal.get(terminal, []), terminals_config)
        append_entry(terminal, by_terminal.get(terminal, []), city=meta.get("city", "Gdansk"))

    plszz_meta = terminals_config.get("PLSZZ", {})
    plszz_counts = _activity_counts(plszz_moves, now=now)
    catalog.append(
        {
            "terminal": "PLSZZ",
            "label": plszz_meta.get("label", "Port Szczecin-Świnoujście"),
            "description_pl": plszz_meta.get("description_pl"),
            "city": "Swinoujscie",
            "lat": plszz_meta.get("lat"),
            "lon": plszz_meta.get("lon"),
            "has_codeco_data": bool(plszz_moves),
            "active_last_hour": bool(plszz_counts["active_last_hour"]),
            "moves_in_last_hour": int(plszz_counts["moves_in_last_hour"]),
            "moves_last_hour_display": int(plszz_counts["moves_last_hour"]),
            "total_moves_24h": int(plszz_counts["total_moves_24h"]),
            "export_moves_24h": int(plszz_counts["export_moves_24h"]),
            "import_moves_24h": int(plszz_counts["import_moves_24h"]),
            "truck_demand_hint": truck_demand_hint(
                moves_last_hour=int(plszz_counts["moves_last_hour"]),
                full_moves=int(plszz_counts.get("full_moves_24h") or 0),
            )
            if plszz_counts["active_last_hour"]
            else "idle",
            "corridor": "west_port",
            "data_anchored": data_anchored,
        }
    )

    catalog.sort(
        key=lambda item: (
            0 if item.get("active_last_hour") else 1,
            -(item.get("moves_in_last_hour") or 0),
            item.get("terminal") or "",
        )
    )
    return catalog


def build_approach_zones(
    store: PortDataStore,
    *,
    traffic_events: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """TIR road corridors enriched with live terminal activity and traffic status."""
    catalog = {item["terminal"]: item for item in build_terminals_catalog(store)}
    zones: list[dict[str, Any]] = []
    traffic = traffic_events or []

    for zone in load_approach_zones_config().get("zones") or []:
        terminal = zone.get("terminal")
        terminal_info = catalog.get(terminal, {})
        active = bool(terminal_info.get("active_last_hour"))
        hint = terminal_info.get("truck_demand_hint", "idle")
        roads_status = [
            resolve_road_traffic_status(road, traffic, city=zone.get("city"))
            for road in (zone.get("roads_pl") or [])
        ]
        road_statuses = [item["status"] for item in roads_status]
        corridor_geom = _enrich_corridor_geometry(zone, traffic)
        zones.append(
            {
                **zone,
                **corridor_geom,
                "active_last_hour": active,
                "moves_in_last_hour": terminal_info.get("moves_in_last_hour", 0),
                "truck_demand_hint": hint,
                "roads_status": roads_status,
                "corridor_status": _worst_road_status(road_statuses),
                "corridor_status_pl": ROAD_STATUS_LABELS_PL[_worst_road_status(road_statuses)],
            }
        )

    return zones


def build_city_port_dashboard(
    store: PortDataStore,
    *,
    traffic_events: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Grouped port operations view: terminals + TIR road status per city."""
    catalog = build_terminals_catalog(store)
    zones = build_approach_zones(store, traffic_events=traffic_events)
    traffic = traffic_events or []
    terminals_config = store.terminals_config.get("terminals") or {}
    dashboard: list[dict[str, Any]] = []

    for group in CITY_PORT_GROUPS:
        group_cities = set(group["cities"])
        city_terminals = [item for item in catalog if item.get("city") in group_cities]
        city_zones = [zone for zone in zones if zone.get("city") in group_cities]
        seen_roads: set[str] = set()
        roads: list[dict[str, Any]] = []
        for zone in city_zones:
            zone_city = zone.get("city")
            for road in zone.get("roads_pl") or []:
                if road in seen_roads:
                    continue
                seen_roads.add(road)
                roads.append(resolve_road_traffic_status(road, traffic, city=zone_city))
        roads.sort(
            key=lambda item: (
                0 if item["status"] == "CRITICAL" else 1 if item["status"] == "CONGESTION" else 2,
                item["road"],
            )
        )
        active_count = sum(1 for item in city_terminals if item.get("active_last_hour"))
        road_statuses = [item["status"] for item in roads]
        dashboard.append(
            {
                "key": group["key"],
                "label": group["label"],
                "cities": list(group["cities"]),
                "active_terminals": active_count,
                "total_terminals": len(city_terminals),
                "roads_status": roads,
                "corridor_status": _worst_road_status(road_statuses),
                "corridor_status_pl": ROAD_STATUS_LABELS_PL[_worst_road_status(road_statuses)],
                "terminals": [
                    {
                        **terminal,
                        "description_pl": terminal.get("description_pl")
                        or (terminals_config.get(terminal["terminal"]) or {}).get("description_pl"),
                        "tir_roads": [
                            road
                            for zone in city_zones
                            if zone.get("terminal") == terminal.get("terminal")
                            for road in (zone.get("roads_pl") or [])
                        ],
                    }
                    for terminal in city_terminals
                ],
                "tir_corridors": city_zones,
            }
        )

    return dashboard


def build_port_map_events(store: PortDataStore) -> list[dict[str, Any]]:
    return (
        build_port_call_events(store)
        + build_container_activity_events(store)
        + build_recent_codeco_move_events(store)
    )


def build_port_summary(
    store: PortDataStore,
    *,
    traffic_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    port_events = build_port_map_events(store)
    calls = [e for e in port_events if e.get("record_kind") == "port_call"]
    activities = [e for e in port_events if e.get("record_kind") == "container_activity"]
    codeco_moves = [e for e in port_events if e.get("record_kind") == "codeco_move"]
    upcoming = [
        c for c in calls if (c.get("context") or {}).get("port_ops", {}).get("call_status") == "expected"
    ]
    in_port = [
        c for c in calls if (c.get("context") or {}).get("port_ops", {}).get("call_status") == "in_port"
    ]
    top_terminals = sorted(
        activities,
        key=lambda item: (item.get("metrics") or {}).get("moves_last_hour", 0),
        reverse=True,
    )[:5]
    return {
        **store.summary(),
        "active_port_calls": len(in_port),
        "upcoming_port_calls": len(upcoming),
        "container_terminals_active": len(activities),
        "codeco_moves_on_map": len(codeco_moves),
        "terminals_catalog": build_terminals_catalog(store),
        "approach_zones": build_approach_zones(store, traffic_events=traffic_events),
        "codeco_hourly_24h": build_codeco_hourly_24h(store),
        "top_terminals": [
            {
                "terminal": (e.get("context") or {}).get("port_ops", {}).get("terminal"),
                "location": (e.get("location") or {}).get("road_name"),
                "moves_last_hour": (e.get("metrics") or {}).get("moves_last_hour"),
                "truck_demand_hint": (e.get("context") or {}).get("port_ops", {}).get("truck_demand_hint"),
                "city": e.get("city"),
            }
            for e in top_terminals
        ],
    }
