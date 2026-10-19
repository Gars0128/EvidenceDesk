import logging
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app import db
from app.document_api import router as document_router
from app.search_api import router as search_router
from app.embeddings import EmbeddingError

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialization failure prevents serving an application with a broken schema.
    await run_in_threadpool(db.initialize)
    yield


app = FastAPI(
    title="EvidenceDesk",
    description="Document ingestion and lexical, vector, and hybrid search with local Ollama embeddings.",
    version="0.3.0",
    lifespan=lifespan,
)
app.include_router(document_router)
app.include_router(search_router)


@app.exception_handler(EmbeddingError)
async def embedding_error(request, exc):
    return JSONResponse(status_code=exc.status, content={"detail": {"code": exc.code, "message": str(exc)}})


@app.exception_handler(psycopg.Error)
async def database_error(request, exc):
    logger.warning("Database operation failed: %s", type(exc).__name__)
    return JSONResponse(
        status_code=503,
        content={"detail": {"code": "database_unavailable", "message": "Database is unavailable. Please try again later."}},
    )


class HealthResponse(BaseModel):
    status: str
    database: str


@app.get("/api/health", response_model=HealthResponse)
def health():
    """Check the live database connection, vector extension, and initial schema."""
    try:
        if not db.check_readiness():
            raise HTTPException(status_code=503, detail="Database schema is not ready")
    except psycopg.Error:
        logger.warning("Database readiness check failed")
        raise HTTPException(status_code=503, detail="Database is unavailable") from None
    return HealthResponse(status="ok", database="ok")
