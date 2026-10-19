"""Real PostgreSQL tests. Only run against a dedicated database ending in _test."""

import hashlib
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
from fastapi.testclient import TestClient

from app import db, documents
from app.ingestion import Page
from app.main import app

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def isolated_database(postgres):
    pass


def create(text="unique document"):
    data = text.encode()
    return documents.create_document("trip.txt", "txt", len(data), hashlib.sha256(data).hexdigest())


def test_full_api_flow_and_stored_source_pages(make_pdf):
    with TestClient(app) as client:
        pdf = make_pdf(["Hotel Aurora " * 200, None, "Free cancellation"])
        response = client.post("/api/documents", files={"file": ("../trip.pdf", pdf)})
        assert response.status_code == 201
        document = response.json()
        assert document["filename"] == "trip.pdf"
        assert document["page_count"] == 3
        assert document["chunk_count"] > 2
        with db.connect() as connection:
            pages = connection.execute("SELECT page_number, text FROM pages WHERE document_id = %s ORDER BY page_number", (document["id"],)).fetchall()
            assert [row[0] for row in pages] == [1, 2, 3]
            assert pages[1][1] == ""
            chunks = connection.execute("SELECT p.page_number, c.text FROM chunks c JOIN pages p ON p.id = c.page_id WHERE p.document_id = %s", (document["id"],)).fetchall()
            assert all(text in pages[number - 1][1] for number, text in chunks)
        duplicate = client.post("/api/documents", files={"file": ("renamed.pdf", pdf)})
        assert duplicate.status_code == 409
        assert duplicate.json()["detail"]["document"]["id"] == document["id"]
        assert len(client.get("/api/documents").json()) == 1


def test_error_survives_and_other_uploads_continue():
    with TestClient(app) as client:
        broken = client.post("/api/documents", files={"file": ("broken.pdf", b"%PDF-1.7\ninvalid")})
        assert broken.status_code == 422
        assert broken.json()["detail"]["document"]["status"] == "error"
        assert client.post("/api/documents", files={"file": ("valid.txt", "Отель Aurora".encode())}).status_code == 201
        listing = client.get("/api/documents").json()
        assert {d["status"] for d in listing} == {"error", "ready"}
        assert client.get("/api/documents?limit=1&offset=1").json()[0]["status"] == "error"


def test_saving_pages_rolls_back_on_failure():
    document, _ = create()
    with pytest.raises(psycopg.errors.UniqueViolation):
        documents.save_pages(document["id"], [Page(1, "First"), Page(1, "Duplicate")])
    saved = documents.get_document(document["id"])
    assert saved["page_count"] == saved["chunk_count"] == 0
    assert saved["status"] == "processing"


def test_concurrent_duplicates_create_one_record():
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: create(), range(4)))
    assert sum(created for _, created in results) == 1
    assert len({document["id"] for document, _ in results}) == 1
    assert len(documents.list_documents()) == 1


def test_restart_recovers_processing_and_preserves_ready():
    interrupted, _ = create("interrupted")
    ready, _ = create("ready")
    documents.save_pages(ready["id"], [Page(1, "Ready text")])
    db.initialize()
    assert documents.get_document(interrupted["id"])["status"] == "error"
    assert documents.get_document(ready["id"])["status"] == "ready"
    assert db.check_readiness()


def test_delete_cascades_to_pages_and_chunks():
    document, _ = create()
    documents.save_pages(document["id"], [Page(1, "Text")])
    with db.connect() as connection:
        connection.execute("DELETE FROM documents WHERE id = %s", (document["id"],))
        assert connection.execute("SELECT count(*) FROM pages").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM chunks").fetchone()[0] == 0
