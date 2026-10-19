import logging
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app import db

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialization failure prevents serving an application with a broken schema.
    await run_in_threadpool(db.initialize)
    yield


app = FastAPI(
    title="EvidenceDesk",
    description="Document answers with verifiable sources. Stage 1: application skeleton.",
    version="0.1.0",
    lifespan=lifespan,
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
