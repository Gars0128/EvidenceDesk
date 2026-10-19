"""Retrieval queries returning page-aware source fragments."""

import json
from uuid import UUID

from psycopg.rows import dict_row

from app import config, embeddings
from app.db import connect


SOURCE_COLUMNS = """c.id AS chunk_id, d.id AS document_id, d.filename,
                    p.page_number, c.chunk_index, c.text"""
SOURCE_JOINS = """FROM chunks c JOIN pages p ON p.id = c.page_id
                  JOIN documents d ON d.id = p.document_id"""


def lexical_search(query: str, limit: int) -> list[dict]:
    with connect() as connection:
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """WITH query AS (
                    SELECT websearch_to_tsquery('english', %s)
                        || websearch_to_tsquery('russian', %s)
                        || websearch_to_tsquery('simple', %s) AS terms
                ) SELECT """ + SOURCE_COLUMNS + """,
                    ts_rank_cd(c.search_vector, query.terms)::double precision AS score
                """ + SOURCE_JOINS + """ CROSS JOIN query
                WHERE d.status = 'ready' AND c.search_vector @@ query.terms
                ORDER BY score DESC, c.id ASC LIMIT %s""",
                (query, query, query, limit),
            )
            return cursor.fetchall()


def index_document(document_id: UUID) -> None:
    """Generate outside a transaction, then save the complete index atomically."""
    with connect() as connection:
        chunks = connection.execute(
            """SELECT c.id, c.text FROM chunks c JOIN pages p ON p.id = c.page_id
               WHERE p.document_id = %s ORDER BY c.id""", (document_id,),
        ).fetchall()
    try:
        vectors = embeddings.embed_texts([text for _, text in chunks])
        with connect() as connection:
            with connection.cursor() as cursor:
                cursor.executemany(
                    "UPDATE chunks SET embedding = %s::vector WHERE id = %s",
                    [(json.dumps(vector), chunk_id) for (chunk_id, _), vector in zip(chunks, vectors, strict=True)],
                )
            connection.execute(
                """UPDATE documents SET embedding_status = 'ready', embedding_error = NULL,
                   embedding_model = %s WHERE id = %s""", (config.EMBEDDING_MODEL, document_id),
            )
    except embeddings.EmbeddingError as exc:
        with connect() as connection:
            connection.execute(
                "UPDATE documents SET embedding_status = 'error', embedding_error = %s WHERE id = %s",
                (str(exc), document_id),
            )
        raise


def corpus_counts() -> tuple[int, int]:
    with connect() as connection:
        return connection.execute(
            """SELECT count(*), count(*) FILTER (
                   WHERE c.embedding IS NOT NULL AND d.embedding_model = %s)
               """ + SOURCE_JOINS + " WHERE d.status = 'ready'",
            (config.EMBEDDING_MODEL,),
        ).fetchone()


def vector_search(vector: list[float], limit: int) -> list[dict]:
    with connect() as connection:
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT " + SOURCE_COLUMNS + ", 1 - (c.embedding <=> %s::vector) AS score "
                + SOURCE_JOINS + """ WHERE d.status = 'ready' AND c.embedding IS NOT NULL
                AND d.embedding_model = %s
                ORDER BY c.embedding <=> %s::vector, c.id ASC LIMIT %s""",
                (json.dumps(vector), config.EMBEDDING_MODEL, json.dumps(vector), limit),
            )
            return cursor.fetchall()


def hybrid_search(query: str, vector: list[float], limit: int) -> list[dict]:
    """Fuse candidate ranks, not incomparable lexical/cosine score scales."""
    candidates = max(20, limit * 4)
    merged = {}
    for kind, hits in (("lexical", lexical_search(query, candidates)),
                       ("vector", vector_search(vector, candidates))):
        for rank, hit in enumerate(hits, start=1):
            result = merged.setdefault(hit["chunk_id"], {**hit, "score": 0.0})
            result["score"] += 1.0 / (60 + rank)
            result[f"{kind}_rank"] = rank
    return sorted(merged.values(), key=lambda hit: (-hit["score"], hit["chunk_id"]))[:limit]
