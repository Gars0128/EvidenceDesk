"""Database helpers using standard libpq PG* environment variables."""

import os
from pathlib import Path

import psycopg


def connect():
    return psycopg.connect(
        os.environ.get("DATABASE_URL", ""),
        connect_timeout=3,
        options="-c statement_timeout=5000 -c lock_timeout=3000",
    )


def initialize() -> None:
    """Apply the initial schema in one transaction; safe on repeated startup."""
    schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    with connect() as connection:
        connection.execute(schema)


def check_readiness() -> bool:
    with connect() as connection:
        row = connection.execute(
            """
            SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')
               AND EXISTS (SELECT 1 FROM schema_version WHERE version = 1)
            """
        ).fetchone()
    return bool(row and row[0])
