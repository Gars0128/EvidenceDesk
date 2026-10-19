"""Database connections and versioned schema initialization."""

import os
from pathlib import Path

import psycopg


APP_DIR = Path(__file__).resolve().parent

MIGRATIONS = (
    (2, APP_DIR / "migrations" / "002_documents.sql"),
)

LATEST_SCHEMA_VERSION = MIGRATIONS[-1][0]


def connect():
    return psycopg.connect(
        os.environ.get("DATABASE_URL", ""),
        connect_timeout=3,
        options="-c statement_timeout=5000 -c lock_timeout=3000",
    )


def initialize() -> None:
    """Apply the initial schema and any pending migrations."""
    with connect() as connection:
        # Serialize schema initialization across application instances.
        connection.execute("SELECT pg_advisory_xact_lock(72419001)")

        initial_schema = (APP_DIR / "schema.sql").read_text(
            encoding="utf-8"
        )
        connection.execute(initial_schema)

        for version, path in MIGRATIONS:
            applied = connection.execute(
                "SELECT 1 FROM schema_version WHERE version = %s",
                (version,),
            ).fetchone()

            if applied:
                continue

            migration_sql = path.read_text(encoding="utf-8")
            connection.execute(migration_sql)

            connection.execute(
                "INSERT INTO schema_version (version) VALUES (%s)",
                (version,),
            )

        # This MVP runs one API process. A restart interrupts synchronous ingestion.
        connection.execute(
            """UPDATE documents SET status = 'error',
               error_message = 'Processing was interrupted by an application restart.'
               WHERE status = 'processing'"""
        )


def check_readiness() -> bool:
    with connect() as connection:
        row = connection.execute(
            """
            SELECT
                EXISTS (
                    SELECT 1
                    FROM pg_extension
                    WHERE extname = 'vector'
                )
                AND EXISTS (
                    SELECT 1
                    FROM schema_version
                    WHERE version = %s
                )
            """,
            (LATEST_SCHEMA_VERSION,),
        ).fetchone()

    return bool(row and row[0])
