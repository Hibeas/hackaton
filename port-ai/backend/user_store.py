"""User accounts — SQLite locally, Supabase/Postgres when DATABASE_URL is set."""

from __future__ import annotations

import logging
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from database_utils import connect_postgres
from observation_store import normalize_database_url

logger = logging.getLogger(__name__)

SERVICE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB_PATH = os.path.join(SERVICE_DIR, "auth.db")

CREATE_TABLE_SQLITE = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    full_name TEXT,
    phone_e164 TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""

CREATE_TABLE_POSTGRES = """
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    full_name TEXT,
    phone_e164 TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

INDEX_EMAIL_SQL = """
CREATE INDEX IF NOT EXISTS idx_users_email ON users (email)
"""

INDEX_PHONE_SQL = """
CREATE INDEX IF NOT EXISTS idx_users_phone ON users (phone_e164)
"""

MIGRATE_PHONE_SQLITE = "ALTER TABLE users ADD COLUMN phone_e164 TEXT"
MIGRATE_PHONE_POSTGRES = "ALTER TABLE users ADD COLUMN IF NOT EXISTS phone_e164 TEXT"


class UserStore:
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
            self._ensure_phone_column_sqlite(connection)
            connection.execute(INDEX_EMAIL_SQL)
            connection.execute(INDEX_PHONE_SQL)
            connection.commit()
        logger.info("UserStore: SQLite (%s)", self.db_path)

    def _ensure_phone_column_sqlite(self, connection: sqlite3.Connection) -> None:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(users)").fetchall()
        }
        if "phone_e164" not in columns:
            connection.execute(MIGRATE_PHONE_SQLITE)

    def _init_postgres(self, database_url: str) -> None:
        try:
            import psycopg2
        except ImportError as exc:
            raise RuntimeError(
                "DATABASE_URL is set but psycopg2 is not installed. "
                "Run: pip install psycopg2-binary"
            ) from exc

        self.backend = "postgres"
        self._psycopg2 = psycopg2
        self._pg_conn = connect_postgres(database_url)
        self._pg_conn.autocommit = True

        with self._pg_conn.cursor() as cursor:
            cursor.execute(CREATE_TABLE_POSTGRES)
            cursor.execute(MIGRATE_PHONE_POSTGRES)
            cursor.execute(INDEX_EMAIL_SQL)
            cursor.execute(INDEX_PHONE_SQL)
        logger.info("UserStore: Supabase/Postgres connected")

    def _sqlite_connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def create_user(
        self,
        *,
        email: str,
        password_hash: str,
        phone_e164: str,
        full_name: str | None = None,
    ) -> dict[str, Any]:
        normalized_email = email.strip().lower()
        user_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc)

        if self.backend == "postgres":
            return self._create_user_postgres(
                user_id=user_id,
                email=normalized_email,
                password_hash=password_hash,
                phone_e164=phone_e164,
                full_name=full_name,
                created_at=created_at,
            )
        return self._create_user_sqlite(
            user_id=user_id,
            email=normalized_email,
            password_hash=password_hash,
            phone_e164=phone_e164,
            full_name=full_name,
            created_at=created_at,
        )

    def _create_user_sqlite(
        self,
        *,
        user_id: str,
        email: str,
        password_hash: str,
        phone_e164: str,
        full_name: str | None,
        created_at: datetime,
    ) -> dict[str, Any]:
        try:
            with self._sqlite_connect() as connection:
                connection.execute(
                    """
                    INSERT INTO users (id, email, password_hash, full_name, phone_e164, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        email,
                        password_hash,
                        full_name,
                        phone_e164,
                        created_at.isoformat(),
                    ),
                )
                connection.commit()
        except sqlite3.IntegrityError as exc:
            raise ValueError("email_taken") from exc
        return self._row_to_user(
            {
                "id": user_id,
                "email": email,
                "full_name": full_name,
                "phone_e164": phone_e164,
                "created_at": created_at.isoformat(),
            }
        )

    def _create_user_postgres(
        self,
        *,
        user_id: str,
        email: str,
        password_hash: str,
        phone_e164: str,
        full_name: str | None,
        created_at: datetime,
    ) -> dict[str, Any]:
        try:
            with self._pg_conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO users (id, email, password_hash, full_name, phone_e164, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id, email, full_name, phone_e164, created_at
                    """,
                    (user_id, email, password_hash, full_name, phone_e164, created_at),
                )
                row = cursor.fetchone()
        except self._psycopg2.IntegrityError as exc:
            raise ValueError("email_taken") from exc
        return self._row_to_user(
            {
                "id": str(row[0]),
                "email": row[1],
                "full_name": row[2],
                "phone_e164": row[3],
                "created_at": row[4].isoformat() if row[4] else created_at.isoformat(),
            }
        )

    def get_by_email(self, email: str) -> dict[str, Any] | None:
        normalized = email.strip().lower()
        if self.backend == "postgres":
            with self._pg_conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, email, password_hash, full_name, phone_e164, created_at
                    FROM users WHERE email = %s
                    """,
                    (normalized,),
                )
                row = cursor.fetchone()
                if not row:
                    return None
                return {
                    "id": str(row[0]),
                    "email": row[1],
                    "password_hash": row[2],
                    "full_name": row[3],
                    "phone_e164": row[4],
                    "created_at": row[5].isoformat() if row[5] else None,
                }

        with self._sqlite_connect() as connection:
            row = connection.execute(
                """
                SELECT id, email, password_hash, full_name, phone_e164, created_at
                FROM users WHERE email = ?
                """,
                (normalized,),
            ).fetchone()
            if row is None:
                return None
            return dict(row)

    def get_by_id(self, user_id: str) -> dict[str, Any] | None:
        if self.backend == "postgres":
            with self._pg_conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, email, password_hash, full_name, phone_e164, created_at
                    FROM users WHERE id = %s
                    """,
                    (user_id,),
                )
                row = cursor.fetchone()
                if not row:
                    return None
                return {
                    "id": str(row[0]),
                    "email": row[1],
                    "password_hash": row[2],
                    "full_name": row[3],
                    "phone_e164": row[4],
                    "created_at": row[5].isoformat() if row[5] else None,
                }

        with self._sqlite_connect() as connection:
            row = connection.execute(
                """
                SELECT id, email, password_hash, full_name, phone_e164, created_at
                FROM users WHERE id = ?
                """,
                (user_id,),
            ).fetchone()
            if row is None:
                return None
            return dict(row)

    def _row_to_user(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "email": row["email"],
            "full_name": row.get("full_name"),
            "phone_e164": row.get("phone_e164"),
            "created_at": row.get("created_at"),
        }


user_store = UserStore()
