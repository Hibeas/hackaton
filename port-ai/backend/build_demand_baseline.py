"""
Builds an expected-port-demand baseline from historical CODECO gate-move data.

Each CODECO row is one container gate move at a terminal, which acts as a proxy
for one truck movement on the terminal access roads. Aggregating these moves by
terminal x day-of-week x hour gives the "expected" truck demand for any timeslot.
The live API uses this baseline to decide whether current road congestion is a
planned gate peak (normal) or an externally caused anomaly.

Run once (offline) whenever new CODECO exports are available:
    python build_demand_baseline.py
Output: port_demand_baseline.json (loaded by the API at runtime).

WARNING: Terminal -> access-corridor mapping in port_demand.py is an assumption
and must be confirmed with port operations before operational use.
"""

import glob
import json
import os
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd

warnings.simplefilter("ignore")

SERVICE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SERVICE_DIR)
OUTPUT_PATH = os.path.join(SERVICE_DIR, "port_demand_baseline.json")

# CODECO sheet has Polish labels on the first data row; assign stable names.
CODECO_COLUMNS = [
    "terminal_unload",
    "terminal_load",
    "move_time",
    "status",
    "fill_level",
    "port_unload",
    "port_load",
]


def load_codeco_file(path: str) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name="Codeco", header=1, names=CODECO_COLUMNS)

    # The truck-facing terminal is the discharge terminal for imports and the
    # load terminal for exports; exactly one of the two is populated per row.
    df["terminal"] = df["terminal_unload"].fillna(df["terminal_load"])
    df["move_time"] = pd.to_datetime(df["move_time"], errors="coerce")
    df = df.dropna(subset=["move_time", "terminal"])
    df["terminal"] = df["terminal"].astype(str).str.strip()
    return df[["terminal", "move_time", "status"]]


def build_baseline() -> dict:
    # CODECO source files live in the isolated solution data folder (port-ai/data).
    data_dir = os.path.join(REPO_ROOT, "data")
    files = sorted(glob.glob(os.path.join(data_dir, "Codeco-*.xlsx")))
    if not files:
        # Backward-compatible fallback: look directly in the repo root.
        files = sorted(glob.glob(os.path.join(REPO_ROOT, "Codeco-*.xlsx")))
    if not files:
        raise FileNotFoundError(f"No Codeco-*.xlsx files found in {data_dir}")

    frames = [load_codeco_file(path) for path in files]
    data = pd.concat(frames, ignore_index=True)

    data["date"] = data["move_time"].dt.date
    data["dow"] = data["move_time"].dt.dayofweek
    data["hour"] = data["move_time"].dt.hour

    # Daily moves per terminal/date/hour, then a distribution per dow x hour cell.
    daily = (
        data.groupby(["terminal", "date", "dow", "hour"])
        .size()
        .reset_index(name="moves")
    )

    terminals: dict[str, dict] = {}
    for terminal, group in daily.groupby("terminal"):
        cells: dict[str, dict[str, dict]] = {}
        cell_medians: list[float] = []
        for (dow, hour), bucket in group.groupby(["dow", "hour"]):
            counts = bucket["moves"].to_numpy(dtype=float)
            median = float(np.median(counts))
            cells.setdefault(str(int(dow)), {})[str(int(hour))] = {
                "median": round(median, 1),
                "mean": round(float(np.mean(counts)), 1),
                "p95": round(float(np.percentile(counts, 95)), 1),
                "n_days": int(counts.size),
            }
            cell_medians.append(median)

        terminals[terminal] = {
            "total_moves": int(group["moves"].sum()),
            "peak_hourly_median": round(max(cell_medians), 1) if cell_medians else 0.0,
            "by_dow_hour": cells,
        }

    observed_dates = sorted(str(d) for d in data["date"].unique())
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_files": [os.path.basename(f) for f in files],
        "timezone": "Europe/Warsaw (naive local time, as stored in CODECO)",
        "total_moves": int(len(data)),
        "date_range": {
            "from": observed_dates[0] if observed_dates else None,
            "to": observed_dates[-1] if observed_dates else None,
            "days_observed": len(observed_dates),
        },
        "terminals": terminals,
    }


def main() -> None:
    baseline = build_baseline()
    with open(OUTPUT_PATH, "w", encoding="utf-8") as handle:
        json.dump(baseline, handle, ensure_ascii=False, indent=2)

    print(f"Wrote {OUTPUT_PATH}")
    print(f"Total moves: {baseline['total_moves']}")
    print(f"Date range: {baseline['date_range']}")
    for terminal, profile in baseline["terminals"].items():
        print(
            f"  {terminal}: total={profile['total_moves']}, "
            f"peak_hourly_median={profile['peak_hourly_median']}"
        )


if __name__ == "__main__":
    main()
