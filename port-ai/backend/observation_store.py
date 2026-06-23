"""
Time-series store for corridor observations (SQLite locally, Supabase/Postgres in cloud).

The anomaly engine compares current snapshots against 15 / 30 / 60 minute windows.
Retention defaults to 24 hours.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

SERVICE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB_PATH = os.path.join(SERVICE_DIR, "corridor_observations.db")
RETENTION_HOURS = 24

CREATE_TABLE_SQLITE = """
CREATE TABLE IF NOT EXISTS corridor_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    corridor_id TEXT NOT NULL,
    port_id TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
)
"""

CREATE_TABLE_POSTGRES = """
CREATE TABLE IF NOT EXISTS corridor_observations (
    id BIGSERIAL PRIMARY KEY,
    corridor_id TEXT NOT NULL,
    port_id TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    payload_json JSONB NOT NULL
)
"""

INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_corridor_time
ON corridor_observations (corridor_id, observed_at DESC)
"""


from database_utils import connect_postgres


def normalize_database_url(raw_url: str) -> str:
    """Accept SQLAlchemy-style URLs and plain postgres:// from Supabase."""
    url = raw_url.strip()
    if url.startswith("postgresql+asyncpg://"):
        return "postgresql://" + url[len("postgresql+asyncpg://") :]
    if url.startswith("postgres+asyncpg://"):
        return "postgres://" + url[len("postgres+asyncpg://") :]
    if url.startswith("postgresql+psycopg2://"):
        return "postgresql://" + url[len("postgresql+psycopg2://") :]
    return url


def parse_observed_at(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        observed = value
    else:
        observed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    return observed.astimezone(timezone.utc)


class ObservationStore:
    def __init__(
        self,
        database_url: str | None = None,
        db_path: str = DEFAULT_DB_PATH,
    ) -> None:
        env_url = database_url or os.environ.get("DATABASE_URL")
        self.backend = "sqlite"
        self.db_path = db_path
        self._pg_conn = None

        if env_url:
            self._init_postgres(normalize_database_url(env_url))
        else:
            self._init_sqlite()

    @property
    def backend_name(self) -> str:
        return self.backend

    def _init_sqlite(self) -> None:
        self.backend = "sqlite"
        with self._sqlite_connect() as connection:
            connection.execute(CREATE_TABLE_SQLITE)
            connection.execute(INDEX_SQL)
            connection.commit()
        logger.info("ObservationStore: SQLite (%s)", self.db_path)

    def _init_postgres(self, database_url: str) -> None:
        try:
            import psycopg2
            import psycopg2.extras
        except ImportError as exc:
            raise RuntimeError(
                "DATABASE_URL is set but psycopg2 is not installed. "
                "Run: pip install psycopg2-binary"
            ) from exc

        self.backend = "postgres"
        self._psycopg2 = psycopg2
        self._psycopg2_extras = psycopg2.extras
        self._pg_conn = connect_postgres(database_url)
        self._pg_conn.autocommit = True

        with self._pg_conn.cursor() as cursor:
            cursor.execute(CREATE_TABLE_POSTGRES)
            cursor.execute(INDEX_SQL)
        logger.info("ObservationStore: Supabase/Postgres connected")

    def _sqlite_connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def append_batch(self, snapshots: list[dict[str, Any]]) -> None:
        if not snapshots:
            return

        if self.backend == "postgres":
            self._append_batch_postgres(snapshots)
        else:
            self._append_batch_sqlite(snapshots)

        self._purge_old()

    def _append_batch_sqlite(self, snapshots: list[dict[str, Any]]) -> None:
        rows = [
            (
                snapshot["corridor_id"],
                snapshot["port_id"],
                snapshot["timestamp"],
                json.dumps(snapshot, ensure_ascii=False),
            )
            for snapshot in snapshots
        ]
        with self._sqlite_connect() as connection:
            connection.executemany(
                """
                INSERT INTO corridor_observations (corridor_id, port_id, observed_at, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                rows,
            )
            connection.commit()

    def _append_batch_postgres(self, snapshots: list[dict[str, Any]]) -> None:
        rows = [
            (
                snapshot["corridor_id"],
                snapshot["port_id"],
                parse_observed_at(snapshot["timestamp"]),
                self._psycopg2_extras.Json(snapshot),
            )
            for snapshot in snapshots
        ]
        with self._pg_conn.cursor() as cursor:
            self._psycopg2_extras.execute_batch(
                cursor,
                """
                INSERT INTO corridor_observations (corridor_id, port_id, observed_at, payload_json)
                VALUES (%s, %s, %s, %s)
                """,
                rows,
                page_size=100,
            )

    def _purge_old(self) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=RETENTION_HOURS)
        if self.backend == "postgres":
            with self._pg_conn.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM corridor_observations WHERE observed_at < %s",
                    (cutoff,),
                )
            return

        with self._sqlite_connect() as connection:
            connection.execute(
                "DELETE FROM corridor_observations WHERE observed_at < ?",
                (cutoff.isoformat(),),
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
        since = now - timedelta(minutes=minutes)

        if self.backend == "postgres":
            with self._pg_conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT payload_json FROM corridor_observations
                    WHERE corridor_id = %s
                      AND observed_at >= %s
                      AND observed_at <= %s
                    ORDER BY observed_at ASC
                    """,
                    (corridor_id, since, now),
                )
                rows = cursor.fetchall()
            return [self._payload_from_row(row[0]) for row in rows]

        with self._sqlite_connect() as connection:
            rows = connection.execute(
                """
                SELECT payload_json FROM corridor_observations
                WHERE corridor_id = ?
                  AND observed_at >= ?
                  AND observed_at <= ?
                ORDER BY observed_at ASC
                """,
                (corridor_id, since.isoformat(), now.isoformat()),
            ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def list_corridor_timeline(
        self,
        corridor_id: str,
        limit: int = 5000,
    ) -> list[tuple[datetime, dict[str, Any]]]:
        """All observations for a corridor, oldest first."""
        if self.backend == "postgres":
            with self._pg_conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT observed_at, payload_json FROM corridor_observations
                    WHERE corridor_id = %s
                    ORDER BY observed_at ASC
                    LIMIT %s
                    """,
                    (corridor_id, limit),
                )
                rows = cursor.fetchall()
            return [
                (parse_observed_at(row[0]), self._payload_from_row(row[1]))
                for row in rows
            ]

        with self._sqlite_connect() as connection:
            rows = connection.execute(
                """
                SELECT observed_at, payload_json FROM corridor_observations
                WHERE corridor_id = ?
                ORDER BY observed_at ASC
                LIMIT ?
                """,
                (corridor_id, limit),
            ).fetchall()
        return [
            (parse_observed_at(row["observed_at"]), json.loads(row["payload_json"]))
            for row in rows
        ]

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
        window_start = target - timedelta(minutes=tolerance_minutes)
        window_end = target + timedelta(minutes=tolerance_minutes)

        if self.backend == "postgres":
            with self._pg_conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT payload_json FROM corridor_observations
                    WHERE corridor_id = %s
                      AND observed_at BETWEEN %s AND %s
                    ORDER BY ABS(EXTRACT(EPOCH FROM (observed_at - %s::timestamptz))) ASC
                    LIMIT 1
                    """,
                    (corridor_id, window_start, window_end, target),
                )
                row = cursor.fetchone()
            if row is None:
                return None
            return self._payload_from_row(row[0])

        with self._sqlite_connect() as connection:
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
                (
                    corridor_id,
                    window_start.isoformat(),
                    window_end.isoformat(),
                    target.isoformat(),
                ),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row["payload_json"])

    def corridor_count(self) -> int:
        if self.backend == "postgres":
            with self._pg_conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM corridor_observations")
                row = cursor.fetchone()
            return int(row[0]) if row else 0

        with self._sqlite_connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS cnt FROM corridor_observations"
            ).fetchone()
        return int(row["cnt"]) if row else 0

    @staticmethod
    def _payload_from_row(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            return json.loads(value)
        return dict(value)
