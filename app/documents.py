"""Document persistence; each operation owns a short transaction."""

from uuid import UUID

from psycopg.rows import dict_row

from app.db import connect
from app.ingestion import Page, split_text


def create_document(filename: str, file_type: str, size_bytes: int, sha256: str) -> tuple[dict, bool]:
    with connect() as connection:
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """INSERT INTO documents (filename, file_type, size_bytes, sha256)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (sha256) DO NOTHING RETURNING *""",
                (filename, file_type, size_bytes, sha256),
            )
            document = cursor.fetchone()
            if document is not None:
                return document, True
            cursor.execute("SELECT * FROM documents WHERE sha256 = %s", (sha256,))
            document = cursor.fetchone()
            if document is None:
                raise RuntimeError("Duplicate document disappeared during lookup")
            return document, False


DOCUMENT_SELECT = """
    SELECT d.*,
        (SELECT count(*) FROM pages p WHERE p.document_id = d.id) AS page_count,
        (SELECT count(*) FROM chunks c JOIN pages p ON p.id = c.page_id
         WHERE p.document_id = d.id) AS chunk_count
    FROM documents d
"""


def get_document(document_id: UUID) -> dict | None:
    with connect() as connection:
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(DOCUMENT_SELECT + " WHERE d.id = %s", (document_id,))
            return cursor.fetchone()


def list_documents(limit: int = 20, offset: int = 0) -> list[dict]:
    if not 1 <= limit <= 100 or offset < 0:
        raise ValueError("limit must be 1..100 and offset must be non-negative")
    with connect() as connection:
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                DOCUMENT_SELECT + " ORDER BY d.created_at DESC, d.id DESC LIMIT %s OFFSET %s",
                (limit, offset),
            )
            return cursor.fetchall()


def save_pages(document_id: UUID, pages: list[Page]) -> None:
    """Save all pages/chunks and mark ready atomically, or roll everything back."""
    with connect() as connection:
        for page in pages:
            page_id = connection.execute(
                "INSERT INTO pages (document_id, page_number, text) VALUES (%s, %s, %s) RETURNING id",
                (document_id, page.number, page.text),
            ).fetchone()[0]
            chunks = split_text(page.text)
            if chunks:
                with connection.cursor() as cursor:
                    cursor.executemany(
                        "INSERT INTO chunks (page_id, chunk_index, text) VALUES (%s, %s, %s)",
                        [(page_id, index, text) for index, text in enumerate(chunks)],
                    )
        connection.execute(
            "UPDATE documents SET status = 'ready', error_message = NULL WHERE id = %s",
            (document_id,),
        )


def mark_error(document_id: UUID, message: str) -> None:
    with connect() as connection:
        connection.execute(
            "UPDATE documents SET status = 'error', error_message = %s WHERE id = %s",
            (message, document_id),
        )
