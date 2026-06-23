"""Load Random Forest delay regressor and predict long-horizon corridor delays."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

FEATURES = ["lat", "lon", "hour", "day_of_week", "is_weekend"]
SERVICE_DIR = Path(__file__).resolve().parent
DEFAULT_MODEL_PATH = SERVICE_DIR / "data" / "ml" / "traffic_delay_regressor.pkl"

_model: Any | None = None
_model_loaded = False


def ml_enabled() -> bool:
    return os.environ.get("TRAFFIC_ML_ENABLED", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def model_path() -> Path:
    raw = os.environ.get("TRAFFIC_ML_MODEL_PATH", "").strip()
    if raw:
        path = Path(raw)
        if not path.is_absolute():
            path = SERVICE_DIR / path
        return path
    return DEFAULT_MODEL_PATH


def load_model() -> Any | None:
    global _model, _model_loaded
    if _model_loaded:
        return _model
    _model_loaded = True
    if not ml_enabled():
        logger.info("Traffic ML predictor disabled (TRAFFIC_ML_ENABLED=false)")
        return None
    path = model_path()
    if not path.is_file():
        logger.warning("Traffic ML model not found at %s", path)
        return None
    try:
        import joblib

        _model = joblib.load(path)
        logger.info("Traffic ML model loaded from %s", path)
    except Exception as exc:
        logger.warning("Failed to load traffic ML model: %s", exc)
        _model = None
    return _model


def corridor_centroid(bbox: dict[str, float]) -> tuple[float, float]:
    lat = (float(bbox["min_lat"]) + float(bbox["max_lat"])) / 2.0
    lon = (float(bbox["min_lon"]) + float(bbox["max_lon"])) / 2.0
    return lat, lon


def _feature_row(lat: float, lon: float, at_time: datetime) -> dict[str, float]:
    if at_time.tzinfo is None:
        at_time = at_time.replace(tzinfo=timezone.utc)
    local = at_time.astimezone(timezone.utc)
    dow = local.weekday()
    return {
        "lat": lat,
        "lon": lon,
        "hour": float(local.hour),
        "day_of_week": float(dow),
        "is_weekend": float(1 if dow >= 5 else 0),
    }


def predict_point(lat: float, lon: float, at_time: datetime | None = None) -> int | None:
    model = load_model()
    if model is None:
        return None
    target = at_time or datetime.now(timezone.utc)
    row = _feature_row(lat, lon, target)
    try:
        frame = pd.DataFrame([row], columns=FEATURES)
        prediction = model.predict(frame)[0]
        return max(0, int(round(float(prediction))))
    except Exception as exc:
        logger.warning("ML predict failed: %s", exc)
        return None


def predict_corridor_long_term(
    corridor: dict[str, Any],
    *,
    horizon_minutes: int,
    reference: datetime | None = None,
) -> dict[str, Any] | None:
    bbox = corridor.get("bbox")
    if not bbox:
        return None
    model = load_model()
    if model is None:
        return None
    now = reference or datetime.now(timezone.utc)
    target_time = now + timedelta(minutes=horizon_minutes)
    lat, lon = corridor_centroid(bbox)
    predicted = predict_point(lat, lon, target_time)
    if predicted is None:
        return None
    return {
        "corridor_id": corridor.get("id"),
        "horizon_minutes": horizon_minutes,
        "predicted_delay_sec": predicted,
        "method": "ml_historical",
        "confidence": "medium",
        "lat": lat,
        "lon": lon,
        "target_time": target_time.isoformat(),
    }
