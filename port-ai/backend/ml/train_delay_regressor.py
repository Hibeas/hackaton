"""Train traffic delay regressor (TomTom + optional ZTM proxy labels)."""

import argparse
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

TARGET = "delay_seconds"
FEATURES = ["lat", "lon", "hour", "day_of_week", "is_weekend"]
ZTM_FREE_FLOW_KMH = 35.0
ZTM_MAX_DELAY = 350


def parse_timestamps(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True, format="mixed", errors="coerce")


def ztm_delay_proxy(speed_kmh: float) -> int:
    speed = max(0.0, float(speed_kmh or 0))
    if speed >= ZTM_FREE_FLOW_KMH:
        return 0
    ratio = 1.0 - speed / ZTM_FREE_FLOW_KMH
    return int(min(ZTM_MAX_DELAY, round(ratio * ZTM_MAX_DELAY)))


def add_time_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["timestamp"] = parse_timestamps(df["timestamp"])
    df = df.dropna(subset=["timestamp"])
    df["hour"] = df["timestamp"].dt.hour
    df["day_of_week"] = df["timestamp"].dt.dayofweek
    df["is_weekend"] = df["day_of_week"].isin([5, 6]).astype(int)
    return df


def load_dataset(path: str, include_ztm: bool = False) -> pd.DataFrame:
    raw = pd.read_csv(path, low_memory=False)
    raw = raw.dropna(subset=["lat", "lon", "timestamp"])
    if "is_synthetic" not in raw.columns:
        raw["is_synthetic"] = False

    tomtom = raw[raw["source_type"] == "tomtom_traffic_api"].copy()
    tomtom["is_proxy_label"] = False
    frames = [tomtom]

    if include_ztm:
        ztm = raw[raw["source_type"] != "tomtom_traffic_api"].copy()
        ztm = ztm.dropna(subset=["speed_kmh"])
        ztm["delay_seconds"] = ztm["speed_kmh"].apply(ztm_delay_proxy)
        ztm["is_proxy_label"] = True
        frames.append(ztm)

    merged = pd.concat(frames, ignore_index=True)
    merged = add_time_features(merged)
    return merged.dropna(subset=FEATURES + [TARGET])


def main() -> None:
    parser = argparse.ArgumentParser(description="Train traffic delay Random Forest")
    parser.add_argument("--dataset", required=True, help="CSV with lat/lon/timestamp/delay_seconds")
    parser.add_argument("--output", default="../data/ml/traffic_delay_regressor.pkl")
    parser.add_argument("--include-ztm", action="store_true")
    args = parser.parse_args()

    df = load_dataset(args.dataset, include_ztm=args.include_ztm)
    X = df[FEATURES]
    y = df[TARGET]

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    model = RandomForestRegressor(n_estimators=200, random_state=42, n_jobs=-1)
    model.fit(X_train, y_train)

    preds = model.predict(X_test)
    print(f"MAE: {mean_absolute_error(y_test, preds):.1f}s")
    print(f"RMSE: {mean_squared_error(y_test, preds, squared=False):.1f}s")
    print(f"R2: {r2_score(y_test, preds):.3f}")

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, out)
    print(f"Saved model to {out.resolve()}")


if __name__ == "__main__":
    main()
