#!/usr/bin/env python3
"""Apply TMS schema migration to Supabase/Postgres (timestamps + tms_slot_calls)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

SERVICE_DIR = Path(__file__).resolve().parents[1]
MIGRATION_SQL = SERVICE_DIR.parent / "supabase" / "migrate_tms_calls_and_timestamps.sql"


def _load_env() -> None:
    env_path = SERVICE_DIR / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def main() -> int:
    _load_env()
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        print("DATABASE_URL not set (.env)", file=sys.stderr)
        return 1
    if not MIGRATION_SQL.is_file():
        print(f"Missing migration file: {MIGRATION_SQL}", file=sys.stderr)
        return 1

    try:
        import psycopg2
    except ImportError:
        print("Install psycopg2-binary", file=sys.stderr)
        return 1

    sql = MIGRATION_SQL.read_text(encoding="utf-8")
    statements = [chunk.strip() for chunk in sql.split(";") if chunk.strip() and not chunk.strip().startswith("--")]

    print(f"Connecting and applying {len(statements)} statements from {MIGRATION_SQL.name}...")
    conn = psycopg2.connect(database_url, connect_timeout=15)
    conn.autocommit = True
    try:
        with conn.cursor() as cursor:
            for statement in statements:
                cursor.execute(statement)
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'tms_slot_templates'
                ORDER BY ordinal_position
                """
            )
            cols = [row[0] for row in cursor.fetchall()]
            cursor.execute(
                """
                SELECT EXISTS (
                  SELECT 1 FROM information_schema.tables
                  WHERE table_schema = 'public' AND table_name = 'tms_slot_calls'
                )
                """
            )
            calls_exists = cursor.fetchone()[0]
    finally:
        conn.close()

    print("OK — tms_slot_templates columns:", ", ".join(cols))
    print("OK — tms_slot_calls exists:", calls_exists)
    expected = {"created_at", "updated_at", "at_risk_since", "window_start_at", "window_end_at"}
    missing = expected - set(cols)
    if missing:
        print("WARNING: still missing:", ", ".join(sorted(missing)), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
