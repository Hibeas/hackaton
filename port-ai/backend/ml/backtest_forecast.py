"""
Backtest hybrid delay forecasts with synthetic crowd spike + historical replay.

Usage (from port-ai/backend):
  .\\.venv\\Scripts\\python.exe ml/backtest_forecast.py
  .\\.venv\\Scripts\\python.exe ml/backtest_forecast.py --corridor baltic_hub_gate
  .\\.venv\\Scripts\\python.exe ml/backtest_forecast.py --synthetic-only
  .\\.venv\\Scripts\\python.exe ml/backtest_forecast.py --history-only --step 6
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

load_dotenv(BACKEND_DIR / ".env")

from corridor_service import find_corridor_by_id, load_corridor_config
from hybrid_delay_forecaster import (
    DEFAULT_HORIZONS,
    ML_ONLY_MIN_HORIZON,
    build_corridor_forecasts,
)
from kafka_prediction_buffer import KafkaPredictionBuffer
from observation_store import ObservationStore, parse_observed_at
from traffic_ml_predictor import load_model, ml_enabled, model_path

CROWD_DELAY_THRESHOLD_SEC = 600
SHORT_HORIZONS = (10, 15, 20, 30)
ML_HORIZONS = (45, 60, 120, 180)
DEFAULT_HORIZONS_BACKTEST = SHORT_HORIZONS + ML_HORIZONS


@dataclass
class ForecastEval:
    corridor_id: str
    method: str
    horizon_minutes: int
    predicted_sec: int
    actual_sec: int
    baseline_sec: int
    scenario: str
    reference_at: str


@dataclass
class MethodStats:
    count: int = 0
    mae_sum: float = 0.0
    sq_err_sum: float = 0.0
    direction_hits: int = 0
    direction_total: int = 0
    crowd_tp: int = 0
    crowd_fp: int = 0
    crowd_fn: int = 0
    crowd_tn: int = 0

    def add(self, predicted: float, actual: float, baseline: float) -> None:
        self.count += 1
        err = predicted - actual
        self.mae_sum += abs(err)
        self.sq_err_sum += err * err

        pred_delta = predicted - baseline
        actual_delta = actual - baseline
        if abs(actual_delta) >= 30:
            self.direction_total += 1
            if (pred_delta >= 0) == (actual_delta >= 0):
                self.direction_hits += 1

        pred_crowd = predicted >= CROWD_DELAY_THRESHOLD_SEC
        actual_crowd = actual >= CROWD_DELAY_THRESHOLD_SEC
        if pred_crowd and actual_crowd:
            self.crowd_tp += 1
        elif pred_crowd and not actual_crowd:
            self.crowd_fp += 1
        elif not pred_crowd and actual_crowd:
            self.crowd_fn += 1
        else:
            self.crowd_tn += 1

    def summary(self) -> dict[str, Any]:
        if self.count == 0:
            return {"samples": 0}
        mae = self.mae_sum / self.count
        rmse = math.sqrt(self.sq_err_sum / self.count)
        direction = (
            round(100.0 * self.direction_hits / self.direction_total, 1)
            if self.direction_total
            else None
        )
        crowd_precision = (
            round(100.0 * self.crowd_tp / (self.crowd_tp + self.crowd_fp), 1)
            if (self.crowd_tp + self.crowd_fp)
            else None
        )
        crowd_recall = (
            round(100.0 * self.crowd_tp / (self.crowd_tp + self.crowd_fn), 1)
            if (self.crowd_tp + self.crowd_fn)
            else None
        )
        return {
            "samples": self.count,
            "mae_sec": round(mae, 1),
            "rmse_sec": round(rmse, 1),
            "direction_accuracy_pct": direction,
            "crowd_precision_pct": crowd_precision,
            "crowd_recall_pct": crowd_recall,
            "crowd_threshold_sec": CROWD_DELAY_THRESHOLD_SEC,
        }


def _metric_delay(snapshot: dict[str, Any] | None) -> int:
    if not snapshot:
        return 0
    metrics = snapshot.get("metrics") or {}
    return int(metrics.get("total_delay_sec") or metrics.get("max_delay_sec") or 0)


def inject_synthetic_crowd(
    buffer: KafkaPredictionBuffer,
    *,
    corridor_id: str,
    port_id: str,
    corridor_name: str,
    reference: datetime,
    peak_delay_sec: int = 960,
    start_delay_sec: int = 90,
    samples: int = 8,
    step_minutes: int = 4,
) -> list[dict[str, Any]]:
    """Ramp delay like rush-hour build-up (synthetic crowd)."""
    snapshots: list[dict[str, Any]] = []
    span_min = step_minutes * max(1, samples - 1)

    for index in range(samples):
        minutes_before = span_min - index * step_minutes
        observed_at = reference - timedelta(minutes=minutes_before)
        ratio = index / max(1, samples - 1)
        delay = start_delay_sec + (peak_delay_sec - start_delay_sec) * ratio
        snapshot = {
            "corridor_id": corridor_id,
            "port_id": port_id,
            "corridor_name": corridor_name,
            "timestamp": observed_at.isoformat(),
            "metrics": {
                "total_delay_sec": delay,
                "max_delay_sec": delay,
                "incident_count": 3 + index * 2,
                "synthetic_crowd": True,
            },
        }
        snapshots.append(snapshot)
        buffer.ingest_snapshot(snapshot)

    return snapshots


def crowd_continues_truth(
    baseline_delay: float,
    peak_delay: float,
    horizon_minutes: int,
    span_minutes: int,
) -> int:
    """If crowd kept building at the same ramp rate for horizon minutes."""
    if span_minutes <= 0:
        return int(round(peak_delay))
    slope = (peak_delay - baseline_delay) / span_minutes
    projected = peak_delay + slope * horizon_minutes
    return int(round(max(0.0, min(3600.0, projected))))


def run_synthetic_crowd_backtest(
    *,
    corridor_id: str,
    horizons: tuple[int, ...],
    peak_delay_sec: int,
) -> list[ForecastEval]:
    port, corridor = find_corridor_by_id(corridor_id)
    reference = datetime.now(timezone.utc)
    buffer = KafkaPredictionBuffer(retention_minutes=45)
    span_min = 4 * 7

    inject_synthetic_crowd(
        buffer,
        corridor_id=corridor_id,
        port_id=str(port["id"]),
        corridor_name=str(corridor.get("name") or corridor_id),
        reference=reference,
        peak_delay_sec=peak_delay_sec,
    )

    forecasts = build_corridor_forecasts(
        buffer=buffer,
        observation_store=None,
        horizons=horizons,
        corridor_id=corridor_id,
        reference=reference,
    )
    baseline = 90
    peak = peak_delay_sec
    results: list[ForecastEval] = []

    for item in forecasts:
        horizon = int(item["horizon_minutes"])
        predicted = int(item["predicted_delay_sec"])
        actual = crowd_continues_truth(baseline, peak, horizon, span_min)
        results.append(
            ForecastEval(
                corridor_id=corridor_id,
                method=str(item.get("method") or "?"),
                horizon_minutes=horizon,
                predicted_sec=predicted,
                actual_sec=actual,
                baseline_sec=baseline,
                scenario="synthetic_crowd",
                reference_at=reference.isoformat(),
            )
        )

    return results


def _fill_buffer_until(
    buffer: KafkaPredictionBuffer,
    timeline: list[tuple[datetime, dict[str, Any]]],
    reference: datetime,
    lookback_minutes: int = 30,
) -> None:
    cutoff = reference - timedelta(minutes=lookback_minutes)
    for observed_at, payload in timeline:
        if observed_at < cutoff or observed_at > reference:
            continue
        buffer.ingest_snapshot(
            {
                **payload,
                "timestamp": observed_at.isoformat(),
            }
        )


def _actual_at_horizon(
    timeline: list[tuple[datetime, dict[str, Any]]],
    reference: datetime,
    horizon_minutes: int,
    tolerance_minutes: int = 8,
) -> int | None:
    target = reference + timedelta(minutes=horizon_minutes)
    window = timedelta(minutes=tolerance_minutes)
    best: tuple[float, int] | None = None

    for observed_at, payload in timeline:
        if observed_at < target - window or observed_at > target + window:
            continue
        delta = abs((observed_at - target).total_seconds())
        delay = _metric_delay(payload)
        if best is None or delta < best[0]:
            best = (delta, delay)

    return best[1] if best else None


def run_historical_backtest(
    store: ObservationStore,
    *,
    corridor_id: str | None,
    horizons: tuple[int, ...],
    step: int,
    max_samples: int,
    tolerance_minutes: int,
) -> list[ForecastEval]:
    config = load_corridor_config()
    results: list[ForecastEval] = []
    corridors: list[tuple[str, dict[str, Any], dict[str, Any]]] = []

    for port in config.get("ports") or []:
        for corridor in port.get("corridors") or []:
            cid = corridor["id"]
            if corridor_id and cid != corridor_id:
                continue
            corridors.append((cid, port, corridor))

    for cid, port, corridor in corridors:
        timeline = store.list_corridor_timeline(cid)
        if len(timeline) < 40:
            continue

        indices = range(30, min(len(timeline) - 1, 30 + max_samples * step), step)
        for index in indices:
            reference, payload = timeline[index]
            baseline = _metric_delay(payload)
            buffer = KafkaPredictionBuffer(retention_minutes=45)
            _fill_buffer_until(buffer, timeline[: index + 1], reference)

            forecasts = build_corridor_forecasts(
                buffer=buffer,
                observation_store=store,
                horizons=horizons,
                corridor_id=cid,
                reference=reference,
            )

            for item in forecasts:
                horizon = int(item["horizon_minutes"])
                actual = _actual_at_horizon(
                    timeline[index + 1 :],
                    reference,
                    horizon,
                    tolerance_minutes=tolerance_minutes,
                )
                if actual is None:
                    continue
                results.append(
                    ForecastEval(
                        corridor_id=cid,
                        method=str(item.get("method") or "?"),
                        horizon_minutes=horizon,
                        predicted_sec=int(item["predicted_delay_sec"]),
                        actual_sec=actual,
                        baseline_sec=baseline,
                        scenario="historical_replay",
                        reference_at=reference.isoformat(),
                    )
                )

    return results


def aggregate_stats(rows: list[ForecastEval]) -> dict[str, Any]:
    by_method: dict[str, MethodStats] = defaultdict(MethodStats)
    by_scenario: dict[str, dict[str, MethodStats]] = defaultdict(
        lambda: defaultdict(MethodStats)
    )

    for row in rows:
        by_method[row.method].add(row.predicted_sec, row.actual_sec, row.baseline_sec)
        by_scenario[row.scenario][row.method].add(
            row.predicted_sec, row.actual_sec, row.baseline_sec
        )

    return {
        "overall_by_method": {
            method: stats.summary() for method, stats in sorted(by_method.items())
        },
        "by_scenario": {
            scenario: {
                method: stats.summary()
                for method, stats in sorted(methods.items())
            }
            for scenario, methods in sorted(by_scenario.items())
        },
    }


def print_report(
    *,
    rows: list[ForecastEval],
    stats: dict[str, Any],
    ml_loaded: bool,
    model_file: Path,
    corridor_filter: str | None,
) -> None:
    print("=" * 72)
    print("PORT-AI FORECAST BACKTEST")
    print("=" * 72)
    print(f"ML enabled: {ml_enabled()} | model loaded: {ml_loaded} | path: {model_file}")
    if corridor_filter:
        print(f"Corridor filter: {corridor_filter}")
    print(f"Total forecast evaluations: {len(rows)}")
    print(f"Crowd alert threshold: {CROWD_DELAY_THRESHOLD_SEC}s")
    print()

    for scenario, methods in stats.get("by_scenario", {}).items():
        print(f"--- {scenario} ---")
        for method, summary in methods.items():
            if summary.get("samples", 0) == 0:
                continue
            print(
                f"  {method:20s}  n={summary['samples']:4d}  "
                f"MAE={summary['mae_sec']:6.1f}s  RMSE={summary['rmse_sec']:6.1f}s  "
                f"dir={summary.get('direction_accuracy_pct')}%  "
                f"crowd P/R={summary.get('crowd_precision_pct')}/"
                f"{summary.get('crowd_recall_pct')}%"
            )
        print()

    print("--- Interpretacja ---")
    print(
        "  kafka_trend / observation_trend - reaguja na sztuczny tlum i historie opoznien."
    )
    print(
        "  ml_historical - prognoza z godziny/dnia/lokalizacji; nie widzi biezacego spike'a."
    )
    print(
        "  crowd P/R - czy prognoza >= 600s gdy rzeczywistosc >= 600s (alert dispatch)."
    )
    print("=" * 72)


def parse_horizons(raw: str) -> tuple[int, ...]:
    values: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        minute = int(part)
        if 5 <= minute <= 360:
            values.append(minute)
    return tuple(sorted(set(values))) if values else DEFAULT_HORIZONS_BACKTEST


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest Port-AI delay forecasts")
    parser.add_argument(
        "--corridor",
        default="baltic_hub_gate",
        help="Corridor id for synthetic crowd (default: baltic_hub_gate)",
    )
    parser.add_argument(
        "--horizons",
        default=",".join(str(h) for h in DEFAULT_HORIZONS_BACKTEST),
        help="Comma-separated forecast horizons in minutes",
    )
    parser.add_argument("--peak-delay", type=int, default=960, help="Synthetic crowd peak delay (s)")
    parser.add_argument("--synthetic-only", action="store_true")
    parser.add_argument("--history-only", action="store_true")
    parser.add_argument(
        "--step",
        type=int,
        default=6,
        help="Historical replay: every N-th snapshot (~30s refresh → step 6 ≈ 3 min)",
    )
    parser.add_argument("--max-samples", type=int, default=80, help="Max historical anchor points")
    parser.add_argument("--tolerance-min", type=int, default=8, help="Actual match tolerance (min)")
    parser.add_argument(
        "--output",
        default="data/ml/backtest_report.json",
        help="JSON report path (relative to backend/)",
    )
    parser.add_argument(
        "--sqlite",
        action="store_true",
        help="Use local corridor_observations.db instead of DATABASE_URL",
    )
    args = parser.parse_args()

    horizons = parse_horizons(args.horizons)
    rows: list[ForecastEval] = []

    if not args.history_only:
        try:
            rows.extend(
                run_synthetic_crowd_backtest(
                    corridor_id=args.corridor,
                    horizons=horizons,
                    peak_delay_sec=args.peak_delay,
                )
            )
        except ValueError as exc:
            print(f"Synthetic crowd skipped: {exc}", file=sys.stderr)

    if not args.synthetic_only:
        if args.sqlite:
            os.environ.pop("DATABASE_URL", None)
        try:
            store = ObservationStore()
        except RuntimeError as exc:
            print(f"Historical replay skipped: {exc}", file=sys.stderr)
            store = None
        if store is not None:
            print(
                f"Historical replay from {store.backend_name} "
                f"({store.corridor_count()} observation rows)",
                file=sys.stderr,
            )
            rows.extend(
                run_historical_backtest(
                    store,
                    corridor_id=args.corridor or None,
                    horizons=horizons,
                    step=max(1, args.step),
                    max_samples=max(1, args.max_samples),
                    tolerance_minutes=max(1, args.tolerance_min),
                )
            )

    stats = aggregate_stats(rows)
    model = load_model()
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "corridor": args.corridor,
        "horizons": list(horizons),
        "evaluations": len(rows),
        "stats": stats,
        "samples": [
            {
                "scenario": row.scenario,
                "corridor_id": row.corridor_id,
                "method": row.method,
                "horizon_minutes": row.horizon_minutes,
                "predicted_sec": row.predicted_sec,
                "actual_sec": row.actual_sec,
                "baseline_sec": row.baseline_sec,
                "reference_at": row.reference_at,
            }
            for row in rows[:200]
        ],
    }

    out_path = BACKEND_DIR / args.output
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print_report(
        rows=rows,
        stats=stats,
        ml_loaded=model is not None,
        model_file=model_path(),
        corridor_filter=args.corridor,
    )
    print(f"Report saved: {out_path.resolve()}")


if __name__ == "__main__":
    main()
