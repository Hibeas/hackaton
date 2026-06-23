"""Shared Postgres connection helpers."""

from __future__ import annotations

import os


def postgres_connect_timeout_seconds() -> int:
    return int(os.environ.get("DATABASE_CONNECT_TIMEOUT_SEC", "10"))


def connect_postgres(database_url: str):
    try:
        import psycopg2
    except ImportError as exc:
        raise RuntimeError(
            "DATABASE_URL is set but psycopg2 is not installed. "
            "Run: pip install psycopg2-binary"
        ) from exc

    timeout = postgres_connect_timeout_seconds()
    try:
        return psycopg2.connect(database_url, connect_timeout=timeout)
    except Exception as exc:
        raise RuntimeError(
            f"Could not connect to Postgres (DATABASE_URL). {exc}"
        ) from exc
