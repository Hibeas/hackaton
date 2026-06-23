"""
Port-demand context service.

TomTom incidents are the PRIMARY live congestion signal. ZTM municipal feeds
(Gdynia loops, Gdańsk/Szczecin GPS) provide contextual confirmation only.
CODECO gate-move baseline answers whether current congestion matches expected
port truck demand for this timeslot.

Business rule:
    TomTom hot + high port demand  -> NORMAL  (planned gate peak)
    TomTom hot + low  port demand  -> ANOMALY (external cause, TomTom explains why)
    TomTom calm + ZTM congested    -> WATCH   (local signal without TomTom incident)
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from zoneinfo import ZoneInfo

    PORT_TZ = ZoneInfo("Europe/Warsaw")
except Exception:  # pragma: no cover
    PORT_TZ = None

logger = logging.getLogger(__name__)

ENGINE_DATA_DIR = Path(__file__).resolve().parent / "data" / "engine"
BASELINE_PATH = str(ENGINE_DATA_DIR / "port_demand_baseline.json")

TERMINAL_PROFILE: dict[str, dict[str, str]] = {
    "DCT": {"city": "Gdansk", "corridor": "Trasa Sucharskiego"},
    "DBPS": {"city": "Szczecin", "corridor": "Ulica Gdańska"},
    "GCT": {"city": "Gdynia", "corridor": "Estakada Kwiatkowskiego"},
    "BCT": {"city": "Gdynia", "corridor": "Janka Wiśniewskiego"},
}

# TomTom primary thresholds
TOMTOM_HOT_INCIDENTS = 3
TOMTOM_HOT_DELAY_SEC = 300
TOMTOM_HOT_SEVERE_RATIO = 0.45

# ZTM context thresholds (secondary confirmation)
ZTM_CONFIRM_RATIO = 0.25

# Port demand thresholds
DEMAND_HIGH_RATIO = 0.65
DEMAND_LOW_RATIO = 0.40
CONGESTED_STATUSES = {"CONGESTION", "CRITICAL"}

VERDICT_NORMAL = "NORMAL"
VERDICT_ANOMALY = "ANOMALY"
VERDICT_WATCH = "WATCH"
VERDICT_CALM = "CALM"


class PortDemandBaseline:
    def __init__(self, data: dict[str, Any] | None) -> None:
        self._data = data or {}
        self._terminals = self._data.get("terminals", {})

    @property
    def is_loaded(self) -> bool:
        return bool(self._terminals)

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "loaded": self.is_loaded,
            "generated_at": self._data.get("generated_at"),
            "source_files": self._data.get("source_files"),
            "date_range": self._data.get("date_range"),
            "total_moves": self._data.get("total_moves"),
        }

    def expected_terminal_moves(self, terminal: str, dow: int, hour: int) -> float:
        profile = self._terminals.get(terminal)
        if not profile:
            return 0.0
        cell = profile.get("by_dow_hour", {}).get(str(dow), {}).get(str(hour))
        if not cell:
            return 0.0
        return float(cell.get("median", 0.0))

    def terminal_peak(self, terminal: str) -> float:
        profile = self._terminals.get(terminal)
        if not profile:
            return 0.0
        return float(profile.get("peak_hourly_median", 0.0))

    def city_demand_ratio(self, city: str, dow: int, hour: int) -> dict[str, Any]:
        terminals = [
            terminal
            for terminal, profile in TERMINAL_PROFILE.items()
            if profile["city"] == city and terminal in self._terminals
        ]
        expected_now = sum(
            self.expected_terminal_moves(terminal, dow, hour) for terminal in terminals
        )
        peak = sum(self.terminal_peak(terminal) for terminal in terminals)
        ratio = (expected_now / peak) if peak > 0 else None
        return {
            "terminals": terminals,
            "expected_moves_now": round(expected_now, 1),
            "city_peak_moves": round(peak, 1),
            "demand_ratio": round(ratio, 3) if ratio is not None else None,
        }


def load_baseline(path: str = BASELINE_PATH) -> PortDemandBaseline:
    if not os.path.exists(path):
        logger.warning("Port demand baseline not found at %s", path)
        return PortDemandBaseline(None)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return PortDemandBaseline(json.load(handle))
    except Exception as exc:
        logger.warning("Failed to load port demand baseline: %s", exc)
        return PortDemandBaseline(None)


def current_port_time(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(tz=PORT_TZ) if PORT_TZ is not None else datetime.now()
    if PORT_TZ is not None and now.tzinfo is not None:
        return now.astimezone(PORT_TZ)
    return now


def city_tomtom_metrics(
    primary_events: list[dict[str, Any]], city: str
) -> dict[str, Any]:
    city_incidents = [
        event for event in primary_events if event.get("city") == city
    ]
    if not city_incidents:
        return {
            "incident_count": 0,
            "severe_count": 0,
            "total_delay_sec": 0,
            "severe_ratio": None,
            "is_hot": False,
            "top_causes": [],
        }

    severe = [
        event
        for event in city_incidents
        if event.get("status") in CONGESTED_STATUSES
    ]
    total_delay = sum(
        int((event.get("metrics") or {}).get("delay_sec") or 0)
        for event in city_incidents
    )
    severe_ratio = len(severe) / len(city_incidents)

    causes: list[str] = []
    for event in sorted(
        city_incidents,
        key=lambda item: int((item.get("metrics") or {}).get("delay_sec") or 0),
        reverse=True,
    )[:3]:
        metrics = event.get("metrics") or {}
        reason = metrics.get("primary_reason") or metrics.get("category_label") or "?"
        road = (event.get("location") or {}).get("road_name") or "?"
        causes.append(f"{reason} ({road})")

    is_hot = (
        len(city_incidents) >= TOMTOM_HOT_INCIDENTS
        or total_delay >= TOMTOM_HOT_DELAY_SEC
        or severe_ratio >= TOMTOM_HOT_SEVERE_RATIO
    )

    return {
        "incident_count": len(city_incidents),
        "severe_count": len(severe),
        "total_delay_sec": total_delay,
        "severe_ratio": round(severe_ratio, 3),
        "is_hot": is_hot,
        "top_causes": causes,
    }


def city_ztm_context(
    context_events: list[dict[str, Any]], city: str
) -> dict[str, Any]:
    considered = 0
    congested = 0
    for event in context_events:
        if event.get("city") != city:
            continue
        metrics = event.get("metrics") or {}
        if event.get("record_kind") == "vehicle" and metrics.get("is_bus_stop"):
            continue
        considered += 1
        if event.get("status") in CONGESTED_STATUSES:
            congested += 1

    ratio = (congested / considered) if considered else None
    confirms = ratio is not None and ratio >= ZTM_CONFIRM_RATIO
    return {
        "considered": considered,
        "congested": congested,
        "congestion_ratio": round(ratio, 3) if ratio is not None else None,
        "confirms_congestion": confirms,
    }


def _classify(
    tomtom: dict[str, Any],
    demand_ratio: float | None,
    ztm: dict[str, Any],
) -> dict[str, str]:
    is_hot = tomtom["is_hot"]
    ztm_confirms = ztm.get("confirms_congestion", False)
    causes = "; ".join(tomtom["top_causes"]) if tomtom["top_causes"] else ""

    if not is_hot and not ztm_confirms:
        return {
            "verdict": VERDICT_CALM,
            "reason_code": "free_flow",
            "cause": "TomTom: brak powaznych incydentow. ZTM: ruch w normie.",
        }

    if not is_hot and ztm_confirms:
        return {
            "verdict": VERDICT_WATCH,
            "reason_code": "ztm_only_signal",
            "cause": "ZTM wskazuje lokalny zator, TomTom bez incydentow — obserwowac (mozliwy lokalny problem poza zasięgiem TomTom).",
        }

    if demand_ratio is None:
        cause = f"TomTom: {tomtom['incident_count']} incydentow, opoznienie {tomtom['total_delay_sec']} s."
        if causes:
            cause += f" Przyczyny: {causes}."
        if ztm_confirms:
            cause += " ZTM potwierdza zator lokalnie."
        return {
            "verdict": VERDICT_WATCH,
            "reason_code": "tomtom_hot_no_baseline",
            "cause": cause,
        }

    if demand_ratio >= DEMAND_HIGH_RATIO:
        cause = (
            f"TomTom: {tomtom['incident_count']} incydentow ({tomtom['total_delay_sec']} s opoznienia), "
            f"spodziewany popyt portu wysoki ({int(demand_ratio * 100)}% szczytu) — planowy szczyt, nie anomalia."
        )
        if causes:
            cause += f" Zdarzenia: {causes}."
        return {
            "verdict": VERDICT_NORMAL,
            "reason_code": "planned_gate_peak",
            "cause": cause,
        }

    if demand_ratio <= DEMAND_LOW_RATIO:
        cause = (
            f"ANOMALIA: TomTom raportuje {tomtom['incident_count']} incydentow "
            f"({tomtom['total_delay_sec']} s), ale popyt portu niski ({int(demand_ratio * 100)}% szczytu) — "
            f"przyczyna ZEWNETRZNA wzgledem operacji portu."
        )
        if causes:
            cause += f" TomTom: {causes}."
        if ztm_confirms:
            cause += " ZTM potwierdza zator lokalnie."
        return {
            "verdict": VERDICT_ANOMALY,
            "reason_code": "external_cause_confirmed",
            "cause": cause,
        }

    cause = f"TomTom: {tomtom['incident_count']} incydentow. Popyt portu umiarkowany ({int(demand_ratio * 100)}% szczytu)."
    if causes:
        cause += f" Zdarzenia: {causes}."
    return {
        "verdict": VERDICT_WATCH,
        "reason_code": "ambiguous",
        "cause": cause,
    }


def analyze_cities(
    baseline: PortDemandBaseline,
    primary_events: list[dict[str, Any]],
    context_events: list[dict[str, Any]],
    now: datetime | None = None,
) -> dict[str, Any]:
    reference = current_port_time(now)
    dow = reference.weekday()
    hour = reference.hour

    cities = sorted(
        {profile["city"] for profile in TERMINAL_PROFILE.values()}
        | {event.get("city") for event in primary_events if event.get("city")}
        | {event.get("city") for event in context_events if event.get("city")}
    )

    results: list[dict[str, Any]] = []
    for city in cities:
        tomtom = city_tomtom_metrics(primary_events, city)
        ztm = city_ztm_context(context_events, city)
        demand = (
            baseline.city_demand_ratio(city, dow, hour)
            if baseline.is_loaded
            else {
                "terminals": [],
                "expected_moves_now": None,
                "city_peak_moves": None,
                "demand_ratio": None,
            }
        )
        verdict = _classify(tomtom, demand["demand_ratio"], ztm)

        if tomtom["is_hot"]:
            confidence = "high"
        elif ztm["confirms_congestion"]:
            confidence = "medium"
        else:
            confidence = "low"

        results.append(
            {
                "city": city,
                "verdict": verdict["verdict"],
                "reason_code": verdict["reason_code"],
                "cause": verdict["cause"],
                "confidence": confidence,
                "tomtom": tomtom,
                "ztm_context": ztm,
                "expected_demand": demand,
            }
        )

    return {
        "evaluated_at": reference.isoformat(),
        "context": {"day_of_week": dow, "hour": hour},
        "primary_source": "tomtom",
        "context_source": "ztm",
        "baseline": baseline.metadata,
        "cities": results,
    }
