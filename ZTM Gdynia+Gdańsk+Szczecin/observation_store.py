"""
SQLite time-series store for corridor observations.

The anomaly engine compares current snapshots against 15 / 30 / 60 minute windows.
Retention defaults to 24 hours.
"""

import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from pathlib import Path

logger = logging.getLogger(__name__)

ENGINE_DATA_DIR = Path(__file__).resolve().parent / "data" / "engine"
DEFAULT_DB_PATH = str(ENGINE_DATA_DIR / "corridor_observations.db")
RETENTION_HOURS = 24


class ObservationStore:
    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        ENGINE_DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS corridor_observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    corridor_id TEXT NOT NULL,
                    port_id TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_corridor_time
                ON corridor_observations (corridor_id, observed_at)
                """
            )
            connection.commit()

    def append_batch(self, snapshots: list[dict[str, Any]]) -> None:
        if not snapshots:
            return
        rows = [
            (
                snapshot["corridor_id"],
                snapshot["port_id"],
                snapshot["timestamp"],
                json.dumps(snapshot, ensure_ascii=False),
            )
            for snapshot in snapshots
        ]
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO corridor_observations (corridor_id, port_id, observed_at, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                rows,
            )
            connection.commit()
        self._purge_old()

    def _purge_old(self) -> None:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=RETENTION_HOURS)).isoformat()
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM corridor_observations WHERE observed_at < ?",
                (cutoff,),
            )
            connection.commit()

    def get_history(
        self,
        corridor_id: str,
        minutes: int,
        reference: datetime | None = None,
    ) -> list[dict[str, Any]]:
        now = reference or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        since = (now - timedelta(minutes=minutes)).isoformat()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload_json FROM corridor_observations
                WHERE corridor_id = ? AND observed_at >= ?
                ORDER BY observed_at ASC
                """,
                (corridor_id, since),
            ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def snapshot_at_offset(
        self,
        corridor_id: str,
        minutes_ago: int,
        reference: datetime | None = None,
        tolerance_minutes: int = 5,
    ) -> dict[str, Any] | None:
        """Nearest observation around reference - minutes_ago."""
        now = reference or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        target = now - timedelta(minutes=minutes_ago)
        window_start = (target - timedelta(minutes=tolerance_minutes)).isoformat()
        window_end = (target + timedelta(minutes=tolerance_minutes)).isoformat()

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload_json, observed_at FROM corridor_observations
                WHERE corridor_id = ?
                  AND observed_at BETWEEN ? AND ?
                ORDER BY ABS(
                    julianday(observed_at) - julianday(?)
                ) ASC
                LIMIT 1
                """,
                (corridor_id, window_start, window_end, target.isoformat()),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row["payload_json"])

    def corridor_count(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS cnt FROM corridor_observations").fetchone()
        return int(row["cnt"]) if row else 0
