#!/usr/bin/env python3
"""Copy users from local auth.db (SQLite) into Supabase Postgres."""

from __future__ import annotations

import os
import sqlite3
import sys

from dotenv import load_dotenv

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

load_dotenv(os.path.join(BACKEND_DIR, ".env"))

from database_utils import connect_postgres
from observation_store import normalize_database_url


def main() -> int:
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        print("DATABASE_URL is not set.", file=sys.stderr)
        return 1

    auth_db = os.path.join(BACKEND_DIR, "auth.db")
    if not os.path.isfile(auth_db):
        print(f"No local {auth_db} — nothing to sync.", file=sys.stderr)
        return 1

    connection = sqlite3.connect(auth_db)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        "SELECT id, email, password_hash, full_name, phone_e164, created_at FROM users"
    ).fetchall()
    connection.close()

    if not rows:
        print("auth.db has no users.")
        return 0

    pg = connect_postgres(normalize_database_url(database_url))
    pg.autocommit = True
    synced = 0
    with pg.cursor() as cursor:
        for row in rows:
            cursor.execute(
                """
                INSERT INTO users (id, email, password_hash, full_name, phone_e164, created_at)
                VALUES (%s::uuid, %s, %s, %s, %s, %s::timestamptz)
                ON CONFLICT (email) DO UPDATE SET
                    full_name = EXCLUDED.full_name,
                    phone_e164 = COALESCE(EXCLUDED.phone_e164, users.phone_e164)
                """,
                (
                    row["id"],
                    row["email"],
                    row["password_hash"],
                    row["full_name"],
                    row["phone_e164"],
                    row["created_at"],
                ),
            )
            synced += 1

    pg.close()
    print(f"Synced {synced} user(s) to Supabase.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
