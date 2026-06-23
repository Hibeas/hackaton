"""
Port anomaly detection engine.

Compares current corridor state against 15 / 30 / 60 minute history.
Detects operational anomalies that may impact port logistics — not merely
unusual traffic, but deteriorating conditions on key access roads.

Event types align with the product spec:
  - Gwałtowne Pogorszenie
  - Spadek Prędkości
  - Kongestia
  - Trwałe Wąskie Gardło
"""

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from corridor_service import corridor_priority_multiplier
from observation_store import ObservationStore

logger = logging.getLogger(__name__)

EVENT_RAPID = "Gwałtowne Pogorszenie"
EVENT_SPEED_DROP = "Spadek Prędkości"
EVENT_CONGESTION = "Kongestia"
EVENT_PERSISTENT = "Trwałe Wąskie Gardło"

# Demo-tuned thresholds — reduce ZTM GPS noise and severity inflation.
SPEED_DROP_RAPID_PCT = 40.0
SPEED_DROP_MODERATE_PCT = 28.0
CONGESTION_GROWTH_DELTA = 0.25
RAPID_DELAY_ESCALATION_SEC = 300
RAPID_DELAY_SOLO_SEC = 450
RAPID_INCIDENT_SURGE_COUNT = 4
RAPID_INCIDENT_MIN_DELAY_SEC = 120
RAPID_CONG_MIN = 0.35
RAPID_MIN_CONFIRMING_SIGNALS = 2
RAPID_BASE_RAW_SCORE = 38
RAPID_CRISIS_INCIDENTS = 6
RAPID_CRISIS_DELAY_SEC = 250
EVENT_COOLDOWN_MINUTES = 10
COOLDOWN_REASON_CODES = frozenset({"rapid_deterioration", "speed_drop"})
PERSISTENT_MIN_MINUTES = 18
PERSISTENT_CONGESTION_RATIO = 0.35
PERSISTENT_MAX_SPEED = 22.0
PERSISTENT_MIN_DELAY = 120
PERSISTENT_MIN_TOMTOM_DELAY_SEC = 90
TOMTOM_CALM_MAX_DELAY_SEC = 90
GATE_PEAK_DEMAND_RATIO = 0.65
DISPATCH_HOLD_MIN_SEVERITY = 72
DISPATCH_HOLD_MIN_DELAY_SEC = 480
DISPATCH_CAUTION_MIN_SEVERITY = 55
# ZTM persistence contributes at most this many raw-score points (TomTom-primary).
PERSISTENT_ZTM_SCORE_MAX = 8
PERSISTENT_ZTM_RATIO_SCALE = 10
CONGESTION_ZTM_SCORE_MAX = 8
CONGESTION_ZTM_RATIO_SCALE = 12


def _tomtom_stress(metrics: dict[str, Any]) -> tuple[int, int]:
    return (
        int(metrics.get("incident_count") or 0),
        int(metrics.get("total_delay_sec") or 0),
    )


def _tomtom_effective_delay(metrics: dict[str, Any]) -> int:
    delay, max_delay = _tomtom_stress(metrics)[1], int(metrics.get("max_delay_sec") or 0)
    return max(delay, max_delay)


def _has_operational_tomtom_impact(metrics: dict[str, Any]) -> bool:
    """Incidents in bbox only count when TomTom reports meaningful delay."""
    incidents, _ = _tomtom_stress(metrics)
    effective_delay = _tomtom_effective_delay(metrics)
    if effective_delay >= 60:
        return True
    if incidents >= 2 and effective_delay >= 15:
        return True
    if incidents >= 5:
        return True
    return False


def _is_tomtom_calm(metrics: dict[str, Any]) -> bool:
    return not _has_operational_tomtom_impact(metrics)


def _metric(snapshot: dict[str, Any], key: str) -> float | None:
    value = (snapshot.get("metrics") or {}).get(key)
    if value is None:
        return None
    return float(value)


def _pct_drop(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous <= 0:
        return None
    return ((previous - current) / previous) * 100.0


def _pct_rise(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous <= 0:
        return None
    return ((current - previous) / previous) * 100.0


class AnomalyEngine:
    def __init__(self, store: ObservationStore) -> None:
        self.store = store
        self._cooldown_until: dict[str, datetime] = {}

    def evaluate(self, snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        reference = datetime.now(timezone.utc)

        for snapshot in snapshots:
            corridor_id = snapshot["corridor_id"]
            detected = self._detect_for_corridor(snapshot, corridor_id, reference)
            if detected and not self._is_on_cooldown(
                corridor_id, detected["reason_code"], reference
            ):
                self._mark_cooldown(corridor_id, detected["reason_code"], reference)
                events.append(detected)

        events.sort(key=lambda item: item["severity"], reverse=True)
        return events

    def _cooldown_key(self, corridor_id: str, reason_code: str) -> str:
        return f"{corridor_id}|{reason_code}"

    def _is_on_cooldown(
        self, corridor_id: str, reason_code: str, reference: datetime
    ) -> bool:
        if reason_code not in COOLDOWN_REASON_CODES:
            return False
        until = self._cooldown_until.get(self._cooldown_key(corridor_id, reason_code))
        return until is not None and reference < until

    def _mark_cooldown(
        self, corridor_id: str, reason_code: str, reference: datetime
    ) -> None:
        if reason_code not in COOLDOWN_REASON_CODES:
            return
        self._cooldown_until[self._cooldown_key(corridor_id, reason_code)] = (
            reference + timedelta(minutes=EVENT_COOLDOWN_MINUTES)
        )

    def bottlenecks_last_hour(self) -> list[dict[str, Any]]:
        """Rank corridors by cumulative stress over the last 60 minutes."""
        from corridor_service import load_corridor_config

        config = load_corridor_config()
        reference = datetime.now(timezone.utc)
        rankings: list[dict[str, Any]] = []

        for port in config["ports"]:
            for corridor in port["corridors"]:
                corridor_id = corridor["id"]
                history = self.store.get_history(corridor_id, minutes=60, reference=reference)
                if len(history) < 2:
                    continue

                delays = [_metric(item, "total_delay_sec") or 0 for item in history]
                speeds = [_metric(item, "avg_speed_kmh") for item in history if _metric(item, "avg_speed_kmh")]
                incidents = [_metric(item, "incident_count") or 0 for item in history]

                avg_delay = sum(delays) / len(delays)
                max_delay = max(delays)
                max_peak_delay = max(
                    int(_metric(item, "max_delay_sec") or _metric(item, "total_delay_sec") or 0)
                    for item in history
                )
                avg_incidents = sum(incidents) / len(incidents)
                min_speed = min(speeds) if speeds else None

                if max_peak_delay < 45 and avg_delay < 25:
                    continue

                recent = history[-6:]
                if not any(
                    _has_operational_tomtom_impact(item.get("metrics") or {})
                    for item in recent
                ):
                    continue

                score = min(
                    100,
                    int(
                        min(50, avg_delay / 8)
                        + min(30, avg_incidents * 4)
                        + (30 if min_speed is not None and min_speed < 18 else 0)
                    )
                    * corridor_priority_multiplier(corridor),
                )

                rankings.append(
                    {
                        "corridor_id": corridor_id,
                        "corridor_name": corridor["name"],
                        "port_id": port["id"],
                        "port_name": port["name"],
                        "window_minutes": 60,
                        "stress_score": score,
                        "avg_delay_sec": round(avg_delay, 1),
                        "max_delay_sec": int(max_delay),
                        "avg_incident_count": round(avg_incidents, 1),
                        "min_speed_kmh": round(min_speed, 1) if min_speed is not None else None,
                        "samples": len(history),
                    }
                )

        rankings.sort(key=lambda item: item["stress_score"], reverse=True)
        return rankings[:10]

    def _detect_for_corridor(
        self,
        current: dict[str, Any],
        corridor_id: str,
        reference: datetime,
    ) -> dict[str, Any] | None:
        past_15 = self.store.snapshot_at_offset(corridor_id, 15, reference)
        past_30 = self.store.snapshot_at_offset(corridor_id, 30, reference)
        past_60 = self.store.snapshot_at_offset(corridor_id, 60, reference)
        history_30 = self.store.get_history(corridor_id, minutes=30, reference=reference)

        candidates: list[dict[str, Any]] = []

        rapid = self._detect_rapid_deterioration(current, past_15, past_30)
        if rapid:
            candidates.append(rapid)

        speed_drop = self._detect_speed_drop(current, past_15, past_30, past_60)
        if speed_drop:
            candidates.append(speed_drop)

        congestion = self._detect_congestion_growth(current, past_15, past_30)
        if congestion:
            candidates.append(congestion)

        persistent = self._detect_persistent_bottleneck(current, history_30)
        if persistent:
            candidates.append(persistent)

        if not candidates:
            absolute = self._detect_absolute_stress(current)
            if absolute:
                candidates.append(absolute)

        if not candidates:
            return None

        best = max(candidates, key=lambda item: item["_raw_score"])
        if self._should_suppress_false_positive(current, best):
            return None
        return self._finalize_event(current, best, past_15, past_30)

    def _should_suppress_false_positive(
        self,
        current: dict[str, Any],
        detection: dict[str, Any],
    ) -> bool:
        """TomTom-primary: ZTM-only signals without live incidents are not port anomalies."""
        metrics = current.get("metrics") or {}
        if not _has_operational_tomtom_impact(metrics):
            return True

        incidents, delay = _tomtom_stress(metrics)
        demand = metrics.get("demand_ratio")
        if (
            demand is not None
            and demand >= GATE_PEAK_DEMAND_RATIO
            and delay < 120
            and incidents < 3
        ):
            return True

        return False

    def _detect_rapid_deterioration(
        self,
        current: dict[str, Any],
        past_15: dict[str, Any] | None,
        past_30: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if not past_15:
            return None

        cur_speed = _metric(current, "avg_speed_kmh")
        prev_speed = _metric(past_15, "avg_speed_kmh")
        speed_drop = _pct_drop(cur_speed, prev_speed)

        cur_delay = _metric(current, "total_delay_sec") or 0
        prev_delay = _metric(past_15, "total_delay_sec") or 0
        delay_jump = cur_delay - prev_delay

        cur_cong = _metric(current, "congestion_ratio")
        prev_cong = _metric(past_15, "congestion_ratio")
        cong_jump = (cur_cong - prev_cong) if cur_cong is not None and prev_cong is not None else None

        cur_inc = int(_metric(current, "incident_count") or 0)
        prev_inc = int(_metric(past_15, "incident_count") or 0)
        inc_surge = cur_inc - prev_inc

        signals: list[str] = []
        if speed_drop is not None and speed_drop >= SPEED_DROP_RAPID_PCT:
            signals.append("speed")
        if delay_jump >= RAPID_DELAY_ESCALATION_SEC:
            signals.append("delay")
        if (
            cong_jump is not None
            and cong_jump >= CONGESTION_GROWTH_DELTA
            and cur_cong is not None
            and cur_cong >= RAPID_CONG_MIN
        ):
            signals.append("congestion")
        if inc_surge >= RAPID_INCIDENT_SURGE_COUNT and cur_delay >= RAPID_INCIDENT_MIN_DELAY_SEC:
            signals.append("incidents")

        # TomTom-primary: require corroboration; ZTM speed alone is too noisy for rapid alerts.
        triggered = (
            len(signals) >= RAPID_MIN_CONFIRMING_SIGNALS
            or delay_jump >= RAPID_DELAY_SOLO_SEC
            or (cur_inc >= RAPID_CRISIS_INCIDENTS and cur_delay >= RAPID_CRISIS_DELAY_SEC)
        )
        if not triggered:
            return None

        raw = RAPID_BASE_RAW_SCORE
        if speed_drop and "speed" in signals:
            raw += min(18, speed_drop * 0.35)
        if "delay" in signals or delay_jump >= RAPID_DELAY_ESCALATION_SEC:
            raw += min(15, delay_jump / 20)
        if cong_jump and "congestion" in signals:
            raw += min(5, cong_jump * 12)
        if "incidents" in signals:
            raw += min(10, inc_surge * 2)

        return {
            "event_type": EVENT_RAPID,
            "reason_code": "rapid_deterioration",
            "_raw_score": raw,
            "delta_speed_pct": round(speed_drop, 1) if speed_drop else None,
            "delta_delay_sec": int(delay_jump),
            "window_minutes": 15,
        }

    def _detect_speed_drop(
        self,
        current: dict[str, Any],
        past_15: dict[str, Any] | None,
        past_30: dict[str, Any] | None,
        past_60: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        cur_speed = _metric(current, "avg_speed_kmh")
        if cur_speed is None:
            return None

        metrics = current.get("metrics") or {}
        if not _has_operational_tomtom_impact(metrics):
            return None

        for past, window in ((past_15, 15), (past_30, 30), (past_60, 60)):
            if not past:
                continue
            prev_speed = _metric(past, "avg_speed_kmh")
            drop = _pct_drop(cur_speed, prev_speed)
            if drop is not None and drop >= SPEED_DROP_MODERATE_PCT:
                return {
                    "event_type": EVENT_SPEED_DROP,
                    "reason_code": "speed_drop",
                    "_raw_score": 30 + min(28, drop * 0.75),
                    "delta_speed_pct": round(drop, 1),
                    "window_minutes": window,
                }
        return None

    def _detect_congestion_growth(
        self,
        current: dict[str, Any],
        past_15: dict[str, Any] | None,
        past_30: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        cur_cong = _metric(current, "congestion_ratio")
        cur_inc = int(_metric(current, "incident_count") or 0)
        cur_delay = int(_metric(current, "total_delay_sec") or 0)

        if not _has_operational_tomtom_impact(current.get("metrics") or {}):
            return None

        if cur_cong is None and cur_inc < 2:
            return None

        growth_15 = None
        if past_15 and cur_cong is not None:
            prev = _metric(past_15, "congestion_ratio")
            if prev is not None:
                growth_15 = cur_cong - prev

        inc_growth = None
        if past_15:
            prev_inc = int(_metric(past_15, "incident_count") or 0)
            inc_growth = cur_inc - prev_inc

        triggered = (
            (growth_15 is not None and growth_15 >= CONGESTION_GROWTH_DELTA and cur_cong >= 0.30)
            or (inc_growth is not None and inc_growth >= 3 and cur_delay >= 90)
            or (cur_inc >= 5 and cur_delay >= 180)
        )
        if not triggered:
            return None

        raw = (
            28
            + min(CONGESTION_ZTM_SCORE_MAX, (cur_cong or 0) * CONGESTION_ZTM_RATIO_SCALE)
            + min(22, cur_delay / 18)
        )
        return {
            "event_type": EVENT_CONGESTION,
            "reason_code": "congestion_growth",
            "_raw_score": raw,
            "delta_congestion": round(growth_15, 3) if growth_15 is not None else None,
            "window_minutes": 15,
        }

    def _detect_persistent_bottleneck(
        self,
        current: dict[str, Any],
        history_30: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if len(history_30) < 4:
            return None

        congested_samples = 0
        slow_samples = 0
        high_delay_samples = 0

        for item in history_30:
            cong = _metric(item, "congestion_ratio")
            speed = _metric(item, "avg_speed_kmh")
            delay = _metric(item, "total_delay_sec") or 0
            if cong is not None and cong >= PERSISTENT_CONGESTION_RATIO:
                congested_samples += 1
            if speed is not None and speed <= PERSISTENT_MAX_SPEED:
                slow_samples += 1
            if delay >= PERSISTENT_MIN_DELAY:
                high_delay_samples += 1

        ratio = congested_samples / len(history_30)
        duration_estimate = int(len(history_30) * 0.5)
        metrics = current.get("metrics") or {}
        cur_delay = _tomtom_effective_delay(metrics)
        has_tomtom = _has_operational_tomtom_impact(metrics)

        triggered = (
            high_delay_samples / len(history_30) >= 0.5
            or (
                slow_samples / len(history_30) >= 0.60
                and has_tomtom
                and cur_delay >= 150
            )
            or (
                ratio >= 0.70
                and has_tomtom
                and cur_delay >= 240
            )
        )
        if not triggered or duration_estimate < PERSISTENT_MIN_MINUTES / 2:
            return None

        if not has_tomtom:
            return None
        delay_score = min(28, cur_delay / 18) + min(14, max(0, cur_delay - 540) / 35)
        raw = (
            26
            + min(PERSISTENT_ZTM_SCORE_MAX, ratio * PERSISTENT_ZTM_RATIO_SCALE)
            + delay_score
            + min(12, max(0, duration_estimate - 25) * 0.5)
        )
        return {
            "event_type": EVENT_PERSISTENT,
            "reason_code": "persistent_bottleneck",
            "_raw_score": raw,
            "duration_minutes": duration_estimate,
            "window_minutes": 30,
        }

    def _detect_absolute_stress(self, current: dict[str, Any]) -> dict[str, Any] | None:
        """Cold-start fallback when history is too short for trend detection."""
        delay = int(_metric(current, "total_delay_sec") or 0)
        inc = int(_metric(current, "incident_count") or 0)
        speed = _metric(current, "avg_speed_kmh")

        if delay >= 450 or (inc >= 6 and delay >= 180):
            return {
                "event_type": EVENT_CONGESTION,
                "reason_code": "absolute_stress",
                "_raw_score": 42 + min(28, delay / 15),
                "window_minutes": 0,
            }
        if speed is not None and speed <= 12 and delay >= 150:
            return {
                "event_type": EVENT_SPEED_DROP,
                "reason_code": "absolute_slowdown",
                "_raw_score": 32 + min(20, (22 - speed) * 1.6) + min(10, delay / 30),
                "window_minutes": 0,
            }
        return None

    def _finalize_event(
        self,
        current: dict[str, Any],
        detection: dict[str, Any],
        past_15: dict[str, Any] | None,
        past_30: dict[str, Any] | None,
    ) -> dict[str, Any]:
        metrics = current.get("metrics") or {}
        priority = float(current.get("priority_weight") or 0.8)
        raw_score = detection["_raw_score"] * priority
        severity = min(100, max(10, int(raw_score)))

        confidence = self._confidence(current, past_15, past_30)
        summary = self._build_summary(current, detection)
        event_id = self._event_id(current, detection)

        port_context = self._port_context_label(metrics)

        return {
            "id": event_id,
            "timestamp": current["timestamp"],
            "port": current["port_name"],
            "port_id": current["port_id"],
            "roadSegment": current["corridor_name"],
            "corridor_id": current["corridor_id"],
            "geofence_type": current.get("geofence_type"),
            "business_priority": current.get("business_priority"),
            "logistics_weight": current.get("logistics_weight"),
            "eventType": detection["event_type"],
            "reason_code": detection["reason_code"],
            "severity": severity,
            "confidence": round(confidence, 2),
            "summary": summary,
            "port_context": port_context,
            "dispatch_impact": self._dispatch_impact(severity, port_context, metrics),
            "details": {
                "window_minutes": detection.get("window_minutes"),
                "delta_speed_pct": detection.get("delta_speed_pct"),
                "delta_delay_sec": detection.get("delta_delay_sec"),
                "delta_congestion": detection.get("delta_congestion"),
                "duration_minutes": detection.get("duration_minutes"),
                "current_metrics": metrics,
                "top_incident_causes": metrics.get("top_incident_causes") or [],
            },
        }

    def _confidence(
        self,
        current: dict[str, Any],
        past_15: dict[str, Any] | None,
        past_30: dict[str, Any] | None,
    ) -> float:
        metrics = current.get("metrics") or {}
        has_tomtom = int(metrics.get("incident_count") or 0) > 0
        has_ztm = metrics.get("congestion_ratio") is not None or metrics.get("avg_speed_kmh") is not None
        history_depth = sum(1 for item in (past_15, past_30) if item is not None)

        score = 0.50
        if has_tomtom:
            score += 0.30
        if has_ztm:
            score += 0.06
        if has_tomtom and has_ztm and (metrics.get("congestion_ratio") or 0) >= 0.35:
            score += 0.05
        score += history_depth * 0.05
        return min(0.95, score)

    def _port_context_label(self, metrics: dict[str, Any]) -> str:
        demand = metrics.get("demand_ratio")
        if demand is None:
            return "unknown"
        if demand >= 0.65:
            return "expected_gate_peak"
        if demand <= 0.40:
            return "low_port_demand"
        return "moderate_port_demand"

    def _dispatch_impact(
        self,
        severity: int,
        port_context: str,
        metrics: dict[str, Any],
    ) -> str:
        delay = _tomtom_effective_delay(metrics)
        if severity >= DISPATCH_HOLD_MIN_SEVERITY and delay >= DISPATCH_HOLD_MIN_DELAY_SEC:
            return "HOLD_DISPATCH"
        if severity >= DISPATCH_CAUTION_MIN_SEVERITY:
            return "CAUTION"
        if severity >= 45 and port_context == "expected_gate_peak" and delay >= 240:
            return "CAUTION"
        return "MONITOR"

    def _build_summary(self, current: dict[str, Any], detection: dict[str, Any]) -> str:
        corridor = current["corridor_name"]
        port = current["port_name"]
        metrics = current.get("metrics") or {}
        event_type = detection["event_type"]

        parts: list[str] = [f"Na odcinku {corridor} ({port}) wykryto: {event_type}."]

        if detection.get("delta_speed_pct") is not None:
            parts.append(
                f" Średnia prędkość spadła o {abs(detection['delta_speed_pct']):.0f}% "
                f"w ciągu ok. {detection.get('window_minutes', 15)} minut."
            )
        if detection.get("delta_delay_sec") is not None and detection["delta_delay_sec"] > 0:
            parts.append(
                f" Opóźnienie TomTom wzrosło o {detection['delta_delay_sec']} s w tym oknie."
            )
        if detection.get("duration_minutes"):
            parts.append(
                f" Problem utrzymuje się ok. {detection['duration_minutes']} minut."
            )

        delay = int(metrics.get("total_delay_sec") or 0)
        inc = int(metrics.get("incident_count") or 0)
        if delay or inc:
            parts.append(f" Aktualnie: {inc} incydentów, łączne opóźnienie {delay} s.")

        causes = metrics.get("top_incident_causes") or []
        if causes:
            parts.append(f" Przyczyny TomTom: {'; '.join(causes[:2])}.")

        demand = metrics.get("demand_ratio")
        if demand is not None:
            if demand >= 0.65:
                parts.append(
                    " Kontekst portu: wysoki spodziewany ruch bramowy — mimo to nie kierować dodatkowych TIR-ów na ten odcinek."
                )
            elif demand <= 0.40:
                parts.append(
                    " Kontekst portu: niski ruch bramowy — prawdopodobna przyczyna zewnętrzna względem operacji terminala."
                )

        return "".join(parts)

    def _event_id(self, current: dict[str, Any], detection: dict[str, Any]) -> str:
        seed = f"{current['corridor_id']}|{detection['reason_code']}|{current['timestamp'][:16]}"
        digest = hashlib.sha256(seed.encode()).hexdigest()[:10]
        return f"evt_{digest}"
