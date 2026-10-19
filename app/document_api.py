"""Upload and list endpoints. Ingestion runs synchronously in a worker thread."""

import hashlib
import logging
from datetime import datetime
from typing import Literal
from uuid import UUID

import psycopg
from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel

from app import config, documents, search
from app.ingestion import ProcessingError, clean_filename, extract_pages

router = APIRouter(prefix="/api/documents", tags=["documents"])
logger = logging.getLogger(__name__)


class DocumentResponse(BaseModel):
    id: UUID
    filename: str
    file_type: Literal["pdf", "txt"]
    size_bytes: int
    sha256: str
    status: Literal["processing", "ready", "error"]
    error_message: str | None
    created_at: datetime
    page_count: int = 0
    chunk_count: int = 0
    embedding_status: Literal["pending", "ready", "error"] = "pending"
    embedding_error: str | None = None
    embedding_model: str | None = None


def upload_error(status: int, code: str, message: str, document: dict | None = None):
    detail = {"code": code, "message": message}
    if document is not None:
        detail["document"] = jsonable_encoder(DocumentResponse.model_validate(document))
    return HTTPException(status_code=status, detail=detail)


@router.get("", response_model=list[DocumentResponse], responses={503: {"description": "Database unavailable"}})
def list_uploaded_documents(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return documents.list_documents(limit, offset)


@router.post("/{document_id}/index", response_model=DocumentResponse, responses={
    404: {"description": "Document not found"},
    409: {"description": "Document text is not ready"},
    502: {"description": "Embedding provider error"},
    503: {"description": "Ollama/model unavailable, busy service, or database unavailable"},
    504: {"description": "Embedding provider timeout"},
})
def index_uploaded_document(document_id: UUID):
    document = documents.get_document(document_id)
    if document is None:
        raise upload_error(404, "document_not_found", "Document not found.")
    if document["status"] != "ready":
        raise upload_error(409, "document_not_ready", "Only documents with ready text can be indexed.", document)
    if document["embedding_status"] == "ready" and document["embedding_model"] == config.EMBEDDING_MODEL:
        return document
    search.index_document(document_id)
    return documents.get_document(document_id)


@router.post(
    "", status_code=201, response_model=DocumentResponse,
    responses={
        409: {"description": "Duplicate file; includes the existing document"},
        413: {"description": "File exceeds the upload limit"},
        415: {"description": "Unsupported file extension"},
        422: {"description": "Invalid upload or document processing error"},
        500: {"description": "Unexpected processing failure"},
        503: {"description": "Database unavailable"},
    },
)
def upload_document(file: UploadFile = File(...)):
    try:
        return _ingest(file)
    finally:
        file.file.close()


def _ingest(file: UploadFile):
    try:
        filename, kind = clean_filename(file.filename)
    except ProcessingError as exc:
        status = 415 if exc.code == "unsupported_format" else 422
        raise upload_error(status, exc.code, str(exc)) from None

    if file.size is not None and file.size > config.MAX_UPLOAD_BYTES:
        raise upload_error(413, "file_too_large", "The file exceeds the configured upload limit.")
    data = file.file.read(config.MAX_UPLOAD_BYTES + 1)
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise upload_error(413, "file_too_large", "The file exceeds the configured upload limit.")
    if not data:
        raise upload_error(422, "empty_file", "The uploaded file is empty.")

    document, created = documents.create_document(
        filename, kind, len(data), hashlib.sha256(data).hexdigest(),
    )
    if not created:
        existing = documents.get_document(document["id"]) or document
        raise upload_error(409, "duplicate_document", "This file has already been uploaded.", existing)

    document_id = document["id"]
    try:
        pages = extract_pages(data, kind)
        documents.save_pages(document_id, pages)
    except ProcessingError as exc:
        documents.mark_error(document_id, str(exc))
        raise upload_error(422, exc.code, str(exc), documents.get_document(document_id)) from None
    except Exception as exc:
        logger.exception("Document processing failed for %s", document_id)
        try:
            documents.mark_error(document_id, "Document processing failed. Please check the server logs.")
            document.update(status="error", error_message="Document processing failed. Please check the server logs.")
        except psycopg.Error:
            logger.warning("Could not persist document error for %s", document_id)
        if isinstance(exc, psycopg.Error):
            raise
        raise upload_error(500, "processing_failed", "Document processing failed.", document) from None

    return documents.get_document(document_id)
