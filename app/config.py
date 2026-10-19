"""Small, validated ingestion limits shared by the API and parser."""

import os


def positive_int(name: str, default: int) -> int:
    value = int(os.environ.get(name, default))
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


MAX_UPLOAD_BYTES = positive_int("MAX_UPLOAD_BYTES", 10 * 1024 * 1024)
MAX_PDF_PAGES = positive_int("MAX_PDF_PAGES", 300)
MAX_TEXT_CHARS = positive_int("MAX_TEXT_CHARS", 2_000_000)
CHUNK_SIZE = 1200
CHUNK_OVERLAP = 200

# Changing the model/dimensions requires reindexing and a matching SQL migration.
EMBEDDING_MODEL = "embeddinggemma:300m"
EMBEDDING_DIMENSIONS = 768
