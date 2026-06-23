"""TMS data layer — carriers, slot templates, speditions in Postgres/SQLite."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from database_utils import connect_postgres
from observation_store import normalize_database_url
from tms.canonical import CanonicalSlot, CanonicalSpedition, CarrierInfo

logger = logging.getLogger(__name__)

SERVICE_DIR = Path(__file__).resolve().parents[1]
MOCK_DIR = SERVICE_DIR / "data" / "port" / "tms" / "mock_msc"
DEFAULT_DB_PATH = SERVICE_DIR / "tms.db"
LOCAL_TZ = ZoneInfo("Europe/Warsaw")

CREATE_CARRIERS_SQLITE = """
CREATE TABLE IF NOT EXISTS tms_carriers (
    provider_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    adapter TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    description_pl TEXT
)
"""

CREATE_CARRIERS_POSTGRES = """
CREATE TABLE IF NOT EXISTS tms_carriers (
    provider_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    adapter TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    description_pl TEXT
)
"""

CREATE_SLOT_TEMPLATES_SQLITE = """
CREATE TABLE IF NOT EXISTS tms_slot_templates (
    provider_id TEXT NOT NULL,
    slot_id TEXT NOT NULL,
    terminal_code TEXT NOT NULL,
    port_id TEXT NOT NULL,
    start_hour INTEGER NOT NULL,
    start_minute INTEGER NOT NULL DEFAULT 0,
    duration_minutes INTEGER NOT NULL DEFAULT 30,
    container_count INTEGER NOT NULL DEFAULT 1,
    booking_ref TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'confirmed',
    corridor_ids TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    at_risk_since TEXT,
    window_start_at TEXT,
    window_end_at TEXT,
    PRIMARY KEY (provider_id, slot_id),
    FOREIGN KEY (provider_id) REFERENCES tms_carriers(provider_id)
)
"""

CREATE_SLOT_TEMPLATES_POSTGRES = """
CREATE TABLE IF NOT EXISTS tms_slot_templates (
    provider_id TEXT NOT NULL REFERENCES tms_carriers(provider_id),
    slot_id TEXT NOT NULL,
    terminal_code TEXT NOT NULL,
    port_id TEXT NOT NULL,
    start_hour INT NOT NULL,
    start_minute INT NOT NULL DEFAULT 0,
    duration_minutes INT NOT NULL DEFAULT 30,
    container_count INT NOT NULL DEFAULT 1,
    booking_ref TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'confirmed',
    corridor_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    at_risk_since TIMESTAMPTZ,
    window_start_at TIMESTAMPTZ,
    window_end_at TIMESTAMPTZ,
    PRIMARY KEY (provider_id, slot_id)
)
"""

CREATE_SLOT_CALLS_SQLITE = """
CREATE TABLE IF NOT EXISTS tms_slot_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_id TEXT NOT NULL,
    booking_ref TEXT NOT NULL,
    slot_id TEXT NOT NULL,
    spedition_id TEXT,
    phone_e164 TEXT NOT NULL,
    call_sid TEXT,
    call_status TEXT NOT NULL DEFAULT 'initiated',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    answered_at TEXT
)
"""

CREATE_SLOT_CALLS_POSTGRES = """
CREATE TABLE IF NOT EXISTS tms_slot_calls (
    id BIGSERIAL PRIMARY KEY,
    provider_id TEXT NOT NULL,
    booking_ref TEXT NOT NULL,
    slot_id TEXT NOT NULL,
    spedition_id TEXT,
    phone_e164 TEXT NOT NULL,
    call_sid TEXT,
    call_status TEXT NOT NULL DEFAULT 'initiated',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    answered_at TIMESTAMPTZ,
    CONSTRAINT tms_slot_calls_status_check
        CHECK (call_status IN ('initiated', 'answered', 'failed', 'skipped'))
)
"""

INDEX_SLOT_CALLS_ANSWERED = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_tms_slot_calls_one_answered_per_booking
ON tms_slot_calls (booking_ref)
WHERE call_status = 'answered'
"""

INDEX_SLOT_CALLS_ACTIVE = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_tms_slot_calls_one_active_per_booking
ON tms_slot_calls (booking_ref)
WHERE call_status IN ('initiated', 'answered')
"""

INDEX_SLOT_AT_RISK = """
CREATE INDEX IF NOT EXISTS idx_tms_slot_templates_at_risk
ON tms_slot_templates (provider_id, status)
WHERE status = 'at_risk'
"""

CREATE_SPEDITIONS_SQLITE = """
CREATE TABLE IF NOT EXISTS tms_speditions (
    provider_id TEXT NOT NULL,
    spedition_id TEXT NOT NULL,
    company_name TEXT NOT NULL,
    contact_name TEXT NOT NULL,
    phone_e164 TEXT NOT NULL,
    email TEXT,
    PRIMARY KEY (provider_id, spedition_id),
    FOREIGN KEY (provider_id) REFERENCES tms_carriers(provider_id)
)
"""

CREATE_SPEDITIONS_POSTGRES = """
CREATE TABLE IF NOT EXISTS tms_speditions (
    provider_id TEXT NOT NULL REFERENCES tms_carriers(provider_id),
    spedition_id TEXT NOT NULL,
    company_name TEXT NOT NULL,
    contact_name TEXT NOT NULL,
    phone_e164 TEXT NOT NULL,
    email TEXT,
    PRIMARY KEY (provider_id, spedition_id)
)
"""

CREATE_SPEDITION_SLOTS_SQLITE = """
CREATE TABLE IF NOT EXISTS tms_spedition_slots (
    provider_id TEXT NOT NULL,
    spedition_id TEXT NOT NULL,
    slot_id TEXT NOT NULL,
    PRIMARY KEY (provider_id, spedition_id, slot_id),
    FOREIGN KEY (provider_id, spedition_id) REFERENCES tms_speditions(provider_id, spedition_id),
    FOREIGN KEY (provider_id, slot_id) REFERENCES tms_slot_templates(provider_id, slot_id)
)
"""

CREATE_SPEDITION_SLOTS_POSTGRES = """
CREATE TABLE IF NOT EXISTS tms_spedition_slots (
    provider_id TEXT NOT NULL,
    spedition_id TEXT NOT NULL,
    slot_id TEXT NOT NULL,
    PRIMARY KEY (provider_id, spedition_id, slot_id),
    FOREIGN KEY (provider_id, spedition_id) REFERENCES tms_speditions(provider_id, spedition_id),
    FOREIGN KEY (provider_id, slot_id) REFERENCES tms_slot_templates(provider_id, slot_id)
)
"""

INDEX_SLOT_TERMINAL = """
CREATE INDEX IF NOT EXISTS idx_tms_slot_templates_terminal
ON tms_slot_templates (provider_id, terminal_code)
"""

INDEX_SPEDITION_PHONE = """
CREATE INDEX IF NOT EXISTS idx_tms_speditions_phone
ON tms_speditions (phone_e164)
"""


class TmsDatabase:
    def __init__(
        self,
        database_url: str | None = None,
        db_path: Path | str = DEFAULT_DB_PATH,
    ) -> None:
        env_url = database_url or os.environ.get("DATABASE_URL")
        self.backend = "sqlite"
        self.db_path = str(db_path)
        self._pg_conn = None

        if env_url:
            self._init_postgres(normalize_database_url(env_url))
        else:
            self._init_sqlite()

        self._seed_mock_msc_if_empty()

    @property
    def backend_name(self) -> str:
        return self.backend

    def _init_sqlite(self) -> None:
        self.backend = "sqlite"
        with self._sqlite_connect() as connection:
            connection.execute(CREATE_CARRIERS_SQLITE)
            connection.execute(CREATE_SLOT_TEMPLATES_SQLITE)
            connection.execute(CREATE_SPEDITIONS_SQLITE)
            connection.execute(CREATE_SPEDITION_SLOTS_SQLITE)
            connection.execute(CREATE_SLOT_CALLS_SQLITE)
            connection.execute(INDEX_SLOT_TERMINAL)
            connection.execute(INDEX_SPEDITION_PHONE)
            connection.execute(INDEX_SLOT_CALLS_ANSWERED)
            connection.execute(INDEX_SLOT_CALLS_ACTIVE)
            connection.execute(INDEX_SLOT_AT_RISK)
            connection.commit()
        self._migrate_sqlite_columns()
        logger.info("TmsDatabase: SQLite (%s)", self.db_path)

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
            cursor.execute(CREATE_CARRIERS_POSTGRES)
            cursor.execute(CREATE_SLOT_TEMPLATES_POSTGRES)
            cursor.execute(CREATE_SPEDITIONS_POSTGRES)
            cursor.execute(CREATE_SPEDITION_SLOTS_POSTGRES)
            cursor.execute(CREATE_SLOT_CALLS_POSTGRES)
            cursor.execute(INDEX_SLOT_TERMINAL)
            cursor.execute(INDEX_SPEDITION_PHONE)
            cursor.execute(INDEX_SLOT_CALLS_ANSWERED)
            cursor.execute(INDEX_SLOT_CALLS_ACTIVE)
            cursor.execute(INDEX_SLOT_AT_RISK)
        self._migrate_postgres_columns()
        logger.info("TmsDatabase: Supabase/Postgres connected")

    def _sqlite_connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _migrate_postgres_columns(self) -> None:
        statements = [
            "ALTER TABLE tms_slot_templates ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
            "ALTER TABLE tms_slot_templates ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
            "ALTER TABLE tms_slot_templates ADD COLUMN IF NOT EXISTS at_risk_since TIMESTAMPTZ",
            "ALTER TABLE tms_slot_templates ADD COLUMN IF NOT EXISTS window_start_at TIMESTAMPTZ",
            "ALTER TABLE tms_slot_templates ADD COLUMN IF NOT EXISTS window_end_at TIMESTAMPTZ",
        ]
        with self._pg_conn.cursor() as cursor:
            for statement in statements:
                cursor.execute(statement)

    def _migrate_sqlite_columns(self) -> None:
        columns = {
            "created_at": "TEXT",
            "updated_at": "TEXT",
            "at_risk_since": "TEXT",
            "window_start_at": "TEXT",
            "window_end_at": "TEXT",
        }
        with self._sqlite_connect() as connection:
            existing = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(tms_slot_templates)").fetchall()
            }
            for name, definition in columns.items():
                if name not in existing:
                    connection.execute(f"ALTER TABLE tms_slot_templates ADD COLUMN {name} {definition}")
            connection.commit()

    def _parse_optional_timestamp(self, value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        text = str(value).strip()
        if not text:
            return None
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    def _seed_mock_msc_if_empty(self) -> None:
        if self.get_carrier("mock_msc") is not None:
            return
        logger.info("TmsDatabase: seeding mock_msc carrier data")
        carrier = self._read_json("carrier.json")
        slots = self._read_json("slots.json")
        speditions = self._read_json("speditions.json")
        self.upsert_carrier(
            provider_id=str(carrier.get("provider_id") or "mock_msc"),
            display_name=str(carrier.get("display_name") or "Mock MSC"),
            adapter=str(carrier.get("adapter") or "mock_msc_v1"),
            active=bool(carrier.get("active", True)),
            description_pl=carrier.get("description_pl"),
        )
        for template in slots.get("slot_templates") or []:
            self.upsert_slot_template("mock_msc", template)
        for item in speditions.get("speditions") or []:
            slot_ids = [str(sid) for sid in (item.get("slot_ids") or [])]
            self.upsert_spedition("mock_msc", item, slot_ids)

    def _read_json(self, filename: str) -> dict[str, Any]:
        path = MOCK_DIR / filename
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)

    def upsert_carrier(
        self,
        *,
        provider_id: str,
        display_name: str,
        adapter: str,
        active: bool = True,
        description_pl: str | None = None,
    ) -> None:
        if self.backend == "postgres":
            with self._pg_conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO tms_carriers (provider_id, display_name, adapter, active, description_pl)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (provider_id) DO UPDATE SET
                        display_name = EXCLUDED.display_name,
                        adapter = EXCLUDED.adapter,
                        active = EXCLUDED.active,
                        description_pl = EXCLUDED.description_pl
                    """,
                    (provider_id, display_name, adapter, active, description_pl),
                )
            return

        with self._sqlite_connect() as connection:
            connection.execute(
                """
                INSERT INTO tms_carriers (provider_id, display_name, adapter, active, description_pl)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(provider_id) DO UPDATE SET
                    display_name = excluded.display_name,
                    adapter = excluded.adapter,
                    active = excluded.active,
                    description_pl = excluded.description_pl
                """,
                (provider_id, display_name, adapter, int(active), description_pl),
            )
            connection.commit()

    def upsert_slot_template(self, provider_id: str, template: dict[str, Any]) -> None:
        corridor_ids = [str(item) for item in (template.get("corridor_ids") or [])]
        window_start_at = template.get("window_start_at")
        window_end_at = template.get("window_end_at")
        at_risk_since = template.get("at_risk_since")
        if self.backend == "postgres":
            with self._pg_conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO tms_slot_templates (
                        provider_id, slot_id, terminal_code, port_id,
                        start_hour, start_minute, duration_minutes,
                        container_count, booking_ref, status, corridor_ids,
                        window_start_at, window_end_at, at_risk_since, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, NOW())
                    ON CONFLICT (provider_id, slot_id) DO UPDATE SET
                        terminal_code = EXCLUDED.terminal_code,
                        port_id = EXCLUDED.port_id,
                        start_hour = EXCLUDED.start_hour,
                        start_minute = EXCLUDED.start_minute,
                        duration_minutes = EXCLUDED.duration_minutes,
                        container_count = EXCLUDED.container_count,
                        booking_ref = EXCLUDED.booking_ref,
                        status = EXCLUDED.status,
                        corridor_ids = EXCLUDED.corridor_ids,
                        window_start_at = COALESCE(EXCLUDED.window_start_at, tms_slot_templates.window_start_at),
                        window_end_at = COALESCE(EXCLUDED.window_end_at, tms_slot_templates.window_end_at),
                        at_risk_since = COALESCE(EXCLUDED.at_risk_since, tms_slot_templates.at_risk_since),
                        updated_at = NOW()
                    """,
                    (
                        provider_id,
                        str(template["slot_id"]),
                        str(template.get("terminal_code") or ""),
                        str(template.get("port_id") or ""),
                        int(template.get("start_hour") or 0),
                        int(template.get("start_minute") or 0),
                        int(template.get("duration_minutes") or 30),
                        int(template.get("container_count") or 1),
                        str(template.get("booking_ref") or ""),
                        str(template.get("status") or "confirmed"),
                        json.dumps(corridor_ids),
                        window_start_at,
                        window_end_at,
                        at_risk_since,
                    ),
                )
            return

        with self._sqlite_connect() as connection:
            connection.execute(
                """
                INSERT INTO tms_slot_templates (
                    provider_id, slot_id, terminal_code, port_id,
                    start_hour, start_minute, duration_minutes,
                    container_count, booking_ref, status, corridor_ids,
                    window_start_at, window_end_at, at_risk_since, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(provider_id, slot_id) DO UPDATE SET
                    terminal_code = excluded.terminal_code,
                    port_id = excluded.port_id,
                    start_hour = excluded.start_hour,
                    start_minute = excluded.start_minute,
                    duration_minutes = excluded.duration_minutes,
                    container_count = excluded.container_count,
                    booking_ref = excluded.booking_ref,
                    status = excluded.status,
                    corridor_ids = excluded.corridor_ids,
                    window_start_at = COALESCE(excluded.window_start_at, window_start_at),
                    window_end_at = COALESCE(excluded.window_end_at, window_end_at),
                    at_risk_since = COALESCE(excluded.at_risk_since, at_risk_since),
                    updated_at = datetime('now')
                """,
                (
                    provider_id,
                    str(template["slot_id"]),
                    str(template.get("terminal_code") or ""),
                    str(template.get("port_id") or ""),
                    int(template.get("start_hour") or 0),
                    int(template.get("start_minute") or 0),
                    int(template.get("duration_minutes") or 30),
                    int(template.get("container_count") or 1),
                    str(template.get("booking_ref") or ""),
                    str(template.get("status") or "confirmed"),
                    json.dumps(corridor_ids),
                    window_start_at,
                    window_end_at,
                    at_risk_since,
                ),
            )
            connection.commit()

    def mark_slot_at_risk(
        self,
        provider_id: str,
        slot_id: str,
        *,
        at_risk_since: datetime | None = None,
    ) -> None:
        since = at_risk_since or datetime.now(timezone.utc)
        if self.backend == "postgres":
            with self._pg_conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE tms_slot_templates
                    SET status = 'at_risk', at_risk_since = %s, updated_at = NOW()
                    WHERE provider_id = %s AND slot_id = %s
                    """,
                    (since, provider_id, slot_id),
                )
            return

        with self._sqlite_connect() as connection:
            connection.execute(
                """
                UPDATE tms_slot_templates
                SET status = 'at_risk', at_risk_since = ?, updated_at = datetime('now')
                WHERE provider_id = ? AND slot_id = ?
                """,
                (since.isoformat(), provider_id, slot_id),
            )
            connection.commit()

    def booking_has_answered_call(self, booking_ref: str) -> bool:
        if self.backend == "postgres":
            with self._pg_conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT 1 FROM tms_slot_calls
                    WHERE booking_ref = %s AND call_status = 'answered'
                    LIMIT 1
                    """,
                    (booking_ref,),
                )
                return cursor.fetchone() is not None

        with self._sqlite_connect() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM tms_slot_calls
                WHERE booking_ref = ? AND call_status = 'answered'
                LIMIT 1
                """,
                (booking_ref,),
            ).fetchone()
            return row is not None

    def booking_has_active_call(self, booking_ref: str) -> bool:
        if self.backend == "postgres":
            with self._pg_conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT 1 FROM tms_slot_calls
                    WHERE booking_ref = %s AND call_status IN ('initiated', 'answered')
                    LIMIT 1
                    """,
                    (booking_ref,),
                )
                return cursor.fetchone() is not None

        with self._sqlite_connect() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM tms_slot_calls
                WHERE booking_ref = ? AND call_status IN ('initiated', 'answered')
                LIMIT 1
                """,
                (booking_ref,),
            ).fetchone()
            return row is not None

    def record_slot_call(
        self,
        *,
        provider_id: str,
        booking_ref: str,
        slot_id: str,
        spedition_id: str | None,
        phone_e164: str,
        call_sid: str | None,
        call_status: str = "initiated",
        answered_at: datetime | None = None,
    ) -> None:
        if call_status not in {"initiated", "answered", "failed", "skipped"}:
            raise ValueError(f"invalid call_status: {call_status}")

        if self.backend == "postgres":
            with self._pg_conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO tms_slot_calls (
                        provider_id, booking_ref, slot_id, spedition_id,
                        phone_e164, call_sid, call_status, answered_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        provider_id,
                        booking_ref,
                        slot_id,
                        spedition_id,
                        phone_e164,
                        call_sid,
                        call_status,
                        answered_at,
                    ),
                )
            return

        with self._sqlite_connect() as connection:
            connection.execute(
                """
                INSERT INTO tms_slot_calls (
                    provider_id, booking_ref, slot_id, spedition_id,
                    phone_e164, call_sid, call_status, answered_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    provider_id,
                    booking_ref,
                    slot_id,
                    spedition_id,
                    phone_e164,
                    call_sid,
                    call_status,
                    answered_at.isoformat() if answered_at else None,
                ),
            )
            connection.commit()

    def update_slot_call_from_twilio(
        self,
        *,
        call_sid: str,
        call_status: str,
        twilio_status: str,
    ) -> dict[str, Any] | None:
        if call_status not in {"answered", "failed"}:
            return None

        answered_at = datetime.now(timezone.utc) if call_status == "answered" else None

        if self.backend == "postgres":
            with self._pg_conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, booking_ref, call_status FROM tms_slot_calls
                    WHERE call_sid = %s
                    LIMIT 1
                    """,
                    (call_sid,),
                )
                row = cursor.fetchone()
                if not row:
                    return None
                record_id, booking_ref, current_status = row[0], row[1], row[2]
                if current_status == call_status:
                    return {
                        "id": record_id,
                        "booking_ref": booking_ref,
                        "call_status": current_status,
                        "twilio_status": twilio_status,
                        "updated": False,
                    }
                if call_status == "answered" and self.booking_has_answered_call(str(booking_ref)):
                    cursor.execute(
                        """
                        UPDATE tms_slot_calls
                        SET call_status = 'failed', answered_at = NULL
                        WHERE id = %s
                        """,
                        (record_id,),
                    )
                    return {
                        "id": record_id,
                        "booking_ref": booking_ref,
                        "call_status": "failed",
                        "twilio_status": twilio_status,
                        "updated": True,
                        "note": "booking_already_answered",
                    }
                cursor.execute(
                    """
                    UPDATE tms_slot_calls
                    SET call_status = %s,
                        answered_at = COALESCE(%s, answered_at)
                    WHERE id = %s
                    """,
                    (call_status, answered_at, record_id),
                )
                return {
                    "id": record_id,
                    "booking_ref": booking_ref,
                    "call_status": call_status,
                    "twilio_status": twilio_status,
                    "updated": True,
                }

        with self._sqlite_connect() as connection:
            row = connection.execute(
                """
                SELECT id, booking_ref, call_status FROM tms_slot_calls
                WHERE call_sid = ?
                LIMIT 1
                """,
                (call_sid,),
            ).fetchone()
            if row is None:
                return None
            record_id = row["id"]
            booking_ref = str(row["booking_ref"])
            current_status = str(row["call_status"])
            if current_status == call_status:
                return {
                    "id": record_id,
                    "booking_ref": booking_ref,
                    "call_status": current_status,
                    "twilio_status": twilio_status,
                    "updated": False,
                }
            if call_status == "answered" and self.booking_has_answered_call(booking_ref):
                connection.execute(
                    "UPDATE tms_slot_calls SET call_status = 'failed', answered_at = NULL WHERE id = ?",
                    (record_id,),
                )
                connection.commit()
                return {
                    "id": record_id,
                    "booking_ref": booking_ref,
                    "call_status": "failed",
                    "twilio_status": twilio_status,
                    "updated": True,
                    "note": "booking_already_answered",
                }
            connection.execute(
                """
                UPDATE tms_slot_calls
                SET call_status = ?, answered_at = COALESCE(?, answered_at)
                WHERE id = ?
                """,
                (
                    call_status,
                    answered_at.isoformat() if answered_at else None,
                    record_id,
                ),
            )
            connection.commit()
            return {
                "id": record_id,
                "booking_ref": booking_ref,
                "call_status": call_status,
                "twilio_status": twilio_status,
                "updated": True,
            }

    def upsert_spedition(
        self,
        provider_id: str,
        item: dict[str, Any],
        slot_ids: list[str],
    ) -> None:
        spedition_id = str(item["spedition_id"])
        if self.backend == "postgres":
            with self._pg_conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO tms_speditions (
                        provider_id, spedition_id, company_name, contact_name, phone_e164, email
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (provider_id, spedition_id) DO UPDATE SET
                        company_name = EXCLUDED.company_name,
                        contact_name = EXCLUDED.contact_name,
                        phone_e164 = EXCLUDED.phone_e164,
                        email = EXCLUDED.email
                    """,
                    (
                        provider_id,
                        spedition_id,
                        str(item.get("company_name") or ""),
                        str(item.get("contact_name") or ""),
                        str(item.get("phone_e164") or ""),
                        item.get("email"),
                    ),
                )
                cursor.execute(
                    "DELETE FROM tms_spedition_slots WHERE provider_id = %s AND spedition_id = %s",
                    (provider_id, spedition_id),
                )
                for slot_id in slot_ids:
                    cursor.execute(
                        """
                        INSERT INTO tms_spedition_slots (provider_id, spedition_id, slot_id)
                        VALUES (%s, %s, %s)
                        ON CONFLICT DO NOTHING
                        """,
                        (provider_id, spedition_id, slot_id),
                    )
            return

        with self._sqlite_connect() as connection:
            connection.execute(
                """
                INSERT INTO tms_speditions (
                    provider_id, spedition_id, company_name, contact_name, phone_e164, email
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider_id, spedition_id) DO UPDATE SET
                    company_name = excluded.company_name,
                    contact_name = excluded.contact_name,
                    phone_e164 = excluded.phone_e164,
                    email = excluded.email
                """,
                (
                    provider_id,
                    spedition_id,
                    str(item.get("company_name") or ""),
                    str(item.get("contact_name") or ""),
                    str(item.get("phone_e164") or ""),
                    item.get("email"),
                ),
            )
            connection.execute(
                "DELETE FROM tms_spedition_slots WHERE provider_id = ? AND spedition_id = ?",
                (provider_id, spedition_id),
            )
            for slot_id in slot_ids:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO tms_spedition_slots (provider_id, spedition_id, slot_id)
                    VALUES (?, ?, ?)
                    """,
                    (provider_id, spedition_id, slot_id),
                )
            connection.commit()

    def get_carrier(self, provider_id: str) -> CarrierInfo | None:
        if self.backend == "postgres":
            with self._pg_conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT provider_id, display_name, adapter, active
                    FROM tms_carriers WHERE provider_id = %s
                    """,
                    (provider_id,),
                )
                row = cursor.fetchone()
                if not row:
                    return None
                return CarrierInfo(
                    provider_id=row[0],
                    display_name=row[1],
                    adapter=row[2],
                    active=bool(row[3]),
                )

        with self._sqlite_connect() as connection:
            row = connection.execute(
                """
                SELECT provider_id, display_name, adapter, active
                FROM tms_carriers WHERE provider_id = ?
                """,
                (provider_id,),
            ).fetchone()
            if row is None:
                return None
            return CarrierInfo(
                provider_id=row["provider_id"],
                display_name=row["display_name"],
                adapter=row["adapter"],
                active=bool(row["active"]),
            )

    def list_carriers(self) -> list[CarrierInfo]:
        if self.backend == "postgres":
            with self._pg_conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT provider_id, display_name, adapter, active
                    FROM tms_carriers ORDER BY provider_id
                    """
                )
                return [
                    CarrierInfo(
                        provider_id=row[0],
                        display_name=row[1],
                        adapter=row[2],
                        active=bool(row[3]),
                    )
                    for row in cursor.fetchall()
                ]

        with self._sqlite_connect() as connection:
            rows = connection.execute(
                """
                SELECT provider_id, display_name, adapter, active
                FROM tms_carriers ORDER BY provider_id
                """
            ).fetchall()
            return [
                CarrierInfo(
                    provider_id=row["provider_id"],
                    display_name=row["display_name"],
                    adapter=row["adapter"],
                    active=bool(row["active"]),
                )
                for row in rows
            ]

    def fetch_slot_templates(
        self,
        provider_id: str,
        *,
        terminal_codes: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        if self.backend == "postgres":
            with self._pg_conn.cursor() as cursor:
                if terminal_codes:
                    cursor.execute(
                        """
                        SELECT slot_id, terminal_code, port_id, start_hour, start_minute,
                               duration_minutes, container_count, booking_ref, status, corridor_ids,
                               created_at, updated_at, at_risk_since, window_start_at, window_end_at
                        FROM tms_slot_templates
                        WHERE provider_id = %s AND terminal_code = ANY(%s)
                        ORDER BY start_hour, start_minute
                        """,
                        (provider_id, terminal_codes),
                    )
                else:
                    cursor.execute(
                        """
                        SELECT slot_id, terminal_code, port_id, start_hour, start_minute,
                               duration_minutes, container_count, booking_ref, status, corridor_ids,
                               created_at, updated_at, at_risk_since, window_start_at, window_end_at
                        FROM tms_slot_templates
                        WHERE provider_id = %s
                        ORDER BY start_hour, start_minute
                        """,
                        (provider_id,),
                    )
                return [self._template_row_postgres(row) for row in cursor.fetchall()]

        query = """
            SELECT slot_id, terminal_code, port_id, start_hour, start_minute,
                   duration_minutes, container_count, booking_ref, status, corridor_ids,
                   created_at, updated_at, at_risk_since, window_start_at, window_end_at
            FROM tms_slot_templates
            WHERE provider_id = ?
        """
        params: list[Any] = [provider_id]
        if terminal_codes:
            placeholders = ",".join("?" for _ in terminal_codes)
            query += f" AND terminal_code IN ({placeholders})"
            params.extend(terminal_codes)
        query += " ORDER BY start_hour, start_minute"

        with self._sqlite_connect() as connection:
            rows = connection.execute(query, params).fetchall()
            return [self._template_row_sqlite(dict(row)) for row in rows]

    def fetch_speditions(
        self,
        provider_id: str,
        *,
        slot_ids: list[str] | None = None,
    ) -> list[CanonicalSpedition]:
        if self.backend == "postgres":
            with self._pg_conn.cursor() as cursor:
                if slot_ids:
                    cursor.execute(
                        """
                        SELECT DISTINCT s.spedition_id, s.company_name, s.contact_name,
                               s.phone_e164, s.email
                        FROM tms_speditions s
                        JOIN tms_spedition_slots ss
                          ON ss.provider_id = s.provider_id AND ss.spedition_id = s.spedition_id
                        WHERE s.provider_id = %s AND ss.slot_id = ANY(%s)
                        ORDER BY s.company_name
                        """,
                        (provider_id, slot_ids),
                    )
                else:
                    cursor.execute(
                        """
                        SELECT spedition_id, company_name, contact_name, phone_e164, email
                        FROM tms_speditions
                        WHERE provider_id = %s
                        ORDER BY company_name
                        """,
                        (provider_id,),
                    )
                results: list[CanonicalSpedition] = []
                for row in cursor.fetchall():
                    spedition_id = row[0]
                    assigned = self._slot_ids_for_spedition(provider_id, spedition_id)
                    if slot_ids and not set(slot_ids).intersection(assigned):
                        continue
                    results.append(
                        CanonicalSpedition(
                            spedition_id=str(spedition_id),
                            provider_id=provider_id,
                            company_name=str(row[1]),
                            contact_name=str(row[2]),
                            phone_e164=str(row[3]),
                            slot_ids=assigned,
                            email=row[4],
                        )
                    )
                return results

        query = """
            SELECT DISTINCT s.spedition_id, s.company_name, s.contact_name, s.phone_e164, s.email
            FROM tms_speditions s
        """
        params: list[Any] = [provider_id]
        if slot_ids:
            placeholders = ",".join("?" for _ in slot_ids)
            query += f"""
                JOIN tms_spedition_slots ss
                  ON ss.provider_id = s.provider_id AND ss.spedition_id = s.spedition_id
                WHERE s.provider_id = ? AND ss.slot_id IN ({placeholders})
            """
            params.extend(slot_ids)
        else:
            query += " WHERE s.provider_id = ?"
        query += " ORDER BY s.company_name"

        with self._sqlite_connect() as connection:
            rows = connection.execute(query, params).fetchall()
            results = []
            for row in rows:
                spedition_id = row["spedition_id"]
                assigned = self._slot_ids_for_spedition(provider_id, spedition_id)
                if slot_ids and not set(slot_ids).intersection(assigned):
                    continue
                results.append(
                    CanonicalSpedition(
                        spedition_id=str(spedition_id),
                        provider_id=provider_id,
                        company_name=str(row["company_name"]),
                        contact_name=str(row["contact_name"]),
                        phone_e164=str(row["phone_e164"]),
                        slot_ids=assigned,
                        email=row["email"],
                    )
                )
            return results

    def _slot_ids_for_spedition(self, provider_id: str, spedition_id: str) -> list[str]:
        if self.backend == "postgres":
            with self._pg_conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT slot_id FROM tms_spedition_slots
                    WHERE provider_id = %s AND spedition_id = %s
                    ORDER BY slot_id
                    """,
                    (provider_id, spedition_id),
                )
                return [str(row[0]) for row in cursor.fetchall()]

        with self._sqlite_connect() as connection:
            rows = connection.execute(
                """
                SELECT slot_id FROM tms_spedition_slots
                WHERE provider_id = ? AND spedition_id = ?
                ORDER BY slot_id
                """,
                (provider_id, spedition_id),
            ).fetchall()
            return [str(row["slot_id"]) for row in rows]

    def materialize_slot(self, provider_id: str, template: dict[str, Any], day: date) -> CanonicalSlot:
        duration = int(template["duration_minutes"])
        window_start = self._parse_optional_timestamp(template.get("window_start_at"))
        window_end = self._parse_optional_timestamp(template.get("window_end_at"))

        if window_start is None or window_end is None:
            start_local = datetime(
                day.year,
                day.month,
                day.day,
                int(template["start_hour"]),
                int(template["start_minute"]),
                tzinfo=LOCAL_TZ,
            )
            window_start = start_local.astimezone(timezone.utc)
            window_end = (start_local + timedelta(minutes=duration)).astimezone(timezone.utc)

        slot_id = str(template["slot_id"])
        return CanonicalSlot(
            slot_id=slot_id,
            provider_id=provider_id,
            terminal_code=str(template["terminal_code"]),
            port_id=str(template["port_id"]),
            window_start=window_start.isoformat(),
            window_end=window_end.isoformat(),
            container_count=int(template["container_count"]),
            booking_ref=str(template["booking_ref"]),
            status=str(template["status"]),
            external_ref=f"{provider_id}:{slot_id}",
            corridor_ids=list(template.get("corridor_ids") or []),
        )

    def _template_row_postgres(self, row: tuple[Any, ...]) -> dict[str, Any]:
        corridor_raw = row[9]
        if isinstance(corridor_raw, str):
            corridor_ids = json.loads(corridor_raw)
        else:
            corridor_ids = list(corridor_raw or [])
        return {
            "slot_id": row[0],
            "terminal_code": row[1],
            "port_id": row[2],
            "start_hour": row[3],
            "start_minute": row[4],
            "duration_minutes": row[5],
            "container_count": row[6],
            "booking_ref": row[7],
            "status": row[8],
            "corridor_ids": [str(item) for item in corridor_ids],
            "created_at": row[10].isoformat() if len(row) > 10 and row[10] else None,
            "updated_at": row[11].isoformat() if len(row) > 11 and row[11] else None,
            "at_risk_since": row[12].isoformat() if len(row) > 12 and row[12] else None,
            "window_start_at": row[13].isoformat() if len(row) > 13 and row[13] else None,
            "window_end_at": row[14].isoformat() if len(row) > 14 and row[14] else None,
        }

    def _template_row_sqlite(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            **row,
            "corridor_ids": [str(item) for item in json.loads(row["corridor_ids"] or "[]")],
        }


tms_database = TmsDatabase()
