from datetime import datetime, timezone
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from app import config, db, documents
from app.main import app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(db, "initialize", lambda: None)
    with TestClient(app) as client:
        yield client


@pytest.fixture
def memory_store(monkeypatch):
    records = {}

    def create(filename, kind, size, digest):
        for record in records.values():
            if record["sha256"] == digest:
                return record.copy(), False
        record = dict(id=uuid4(), filename=filename, file_type=kind, size_bytes=size,
                      sha256=digest, status="processing", error_message=None,
                      created_at=datetime.now(timezone.utc), page_count=0, chunk_count=0)
        records[record["id"]] = record
        return record.copy(), True

    def save(document_id, pages):
        record = records[document_id]
        record.update(status="ready", page_count=len(pages), chunk_count=1)

    def error(document_id, message):
        records[document_id].update(status="error", error_message=message)

    monkeypatch.setattr(documents, "create_document", create)
    monkeypatch.setattr(documents, "get_document", lambda key: records[key].copy())
    monkeypatch.setattr(documents, "save_pages", save)
    monkeypatch.setattr(documents, "mark_error", error)
    monkeypatch.setattr(documents, "list_documents", lambda limit, offset: list(records.values())[offset:offset + limit])
    return records


def test_upload_and_list(client, memory_store):
    response = client.post("/api/documents", files={"file": ("trip.txt", "Семейная экскурсия".encode())})
    assert response.status_code == 201
    assert response.json()["status"] == "ready"
    assert response.json()["page_count"] == 1
    listing = client.get("/api/documents").json()
    assert listing[0]["id"] == response.json()["id"]


def test_duplicate_renamed_file(client, memory_store):
    first = client.post("/api/documents", files={"file": ("one.txt", b"Hotel")})
    duplicate = client.post("/api/documents", files={"file": ("two.txt", b"Hotel")})
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["document"]["id"] == first.json()["id"]
    assert len(memory_store) == 1


@pytest.mark.parametrize("filename,data,status,code", [
    ("trip.exe", b"text", 415, "unsupported_format"),
    ("empty.txt", b"", 422, "empty_file"),
])
def test_rejected_before_record_creation(client, memory_store, filename, data, status, code):
    response = client.post("/api/documents", files={"file": (filename, data)})
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code
    assert not memory_store


def test_upload_size_limit(client, memory_store, monkeypatch):
    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", 3)
    assert client.post("/api/documents", files={"file": ("big.txt", b"abcd")}).status_code == 413
    assert not memory_store
    assert client.post("/api/documents", files={"file": ("ok.txt", b"abc")}).status_code == 201


@pytest.mark.parametrize("name,data", [("broken.pdf", b"%PDF-1.7\nbroken"), ("encoding.txt", b"\xff"), ("blank.txt", b" \n")])
def test_error_persisted_and_following_upload_works(client, memory_store, name, data):
    response = client.post("/api/documents", files={"file": (name, data)})
    assert response.status_code == 422
    document = response.json()["detail"]["document"]
    assert document["status"] == "error"
    assert document["error_message"]
    assert document["page_count"] == document["chunk_count"] == 0
    assert client.get("/api/documents").json()[0]["status"] == "error"
    assert client.post("/api/documents", files={"file": ("good.txt", b"Valid text")}).status_code == 201


def test_pdf_upload(client, memory_store, make_pdf):
    response = client.post("/api/documents", files={"file": ("hotel.pdf", make_pdf(["Hotel", "Cancellation"]))})
    assert response.status_code == 201
    assert response.json()["page_count"] == 2


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1", "limit=abc"])
def test_pagination_validation(client, query):
    assert client.get("/api/documents?" + query).status_code == 422


def test_missing_file(client):
    assert client.post("/api/documents").status_code == 422


@pytest.mark.parametrize("method", ["get", "post"])
def test_database_outage_hides_details(client, monkeypatch, method):
    def fail(*args):
        raise psycopg.OperationalError("password=private-secret")
    monkeypatch.setattr(documents, "list_documents", fail)
    monkeypatch.setattr(documents, "create_document", fail)
    response = (client.get("/api/documents") if method == "get" else
                client.post("/api/documents", files={"file": ("trip.txt", b"text")}))
    assert response.status_code == 503
    assert "private-secret" not in response.text


def test_unexpected_failure_marks_error(client, memory_store, monkeypatch):
    def fail(*args):
        raise RuntimeError("internal-path-and-secret")
    monkeypatch.setattr(documents, "save_pages", fail)
    response = client.post("/api/documents", files={"file": ("trip.txt", b"text")})
    assert response.status_code == 500
    assert next(iter(memory_store.values()))["status"] == "error"
    assert "internal-path-and-secret" not in response.text
