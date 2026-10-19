"""Retrieval behavior through the HTTP API and a real PostgreSQL database."""

import pytest
from fastapi.testclient import TestClient

from app.main import app

pytestmark = pytest.mark.integration


@pytest.fixture
def client(postgres):
    with TestClient(app) as client:
        yield client


def test_lexical_search_returns_exact_name_and_source_page(client, make_pdf):
    upload = client.post("/api/documents", files={"file": (
        "hotels.pdf", make_pdf(["Hotel Borealis has a pool.", "Hotel Aurora allows free cancellation."]),
    )})
    assert upload.status_code == 201
    response = client.post("/api/search", json={"query": '"Hotel Aurora"', "mode": "lexical", "top_k": 3})
    assert response.status_code == 200
    hits = response.json()["results"]
    assert len(hits) == 1
    assert hits[0]["document_id"] == upload.json()["id"]
    assert hits[0]["filename"] == "hotels.pdf"
    assert hits[0]["page_number"] == 2
    assert "free cancellation" in hits[0]["text"]


def test_lexical_search_handles_russian_inflections(client):
    client.post("/api/documents", files={"file": ("tour.txt", "Семейная экскурсия по старому городу.".encode())})
    response = client.post("/api/search", json={"query": "семейные экскурсии"})
    assert response.status_code == 200
    assert response.json()["results"][0]["filename"] == "tour.txt"


def test_unmatched_query_and_empty_database_return_no_hits(client):
    assert client.post("/api/search", json={"query": "Aurora"}).json()["results"] == []
    client.post("/api/documents", files={"file": ("trip.txt", b"City walking tour")})
    assert client.post("/api/search", json={"query": "volcano"}).json()["results"] == []


def test_vector_search_after_explicit_indexing(client, fake_ollama):
    upload = client.post("/api/documents", files={"file": ("hotel.txt", b"Free cancellation before arrival.")})
    document_id = upload.json()["id"]
    indexed = client.post(f"/api/documents/{document_id}/index")
    assert indexed.status_code == 200
    assert indexed.json()["embedding_status"] == "ready"
    response = client.post("/api/search", json={"query": "flexible booking", "mode": "vector"})
    assert response.status_code == 200
    hit = response.json()["results"][0]
    assert hit["document_id"] == document_id
    assert hit["score"] == pytest.approx(1.0)


def test_hybrid_promotes_a_fragment_present_in_both_rankings(client, fake_ollama):
    def vector_for(text):
        return ([0.8, 0.6] if "Aurora hotel" in text else [1.0, 0.0]) + [0.0] * 766
    fake_ollama["vector_for"] = vector_for
    shared = client.post("/api/documents", files={"file": ("aurora.txt", b"Aurora hotel free cancellation.")}).json()
    other = client.post("/api/documents", files={"file": ("ocean.txt", b"Ocean resort with a pool.")}).json()
    for document in (shared, other):
        assert client.post(f"/api/documents/{document['id']}/index").status_code == 200
    response = client.post("/api/search", json={"query": "Aurora", "mode": "hybrid", "top_k": 2})
    assert response.status_code == 200
    hits = response.json()["results"]
    assert hits[0]["document_id"] == shared["id"]
    assert hits[0]["lexical_rank"] == 1
    assert hits[0]["vector_rank"] == 2
    assert len({hit["chunk_id"] for hit in hits}) == 2


@pytest.mark.parametrize("mode", ["vector", "hybrid"])
def test_unavailable_ollama_never_falls_back_silently(client, fake_ollama, mode):
    client.post("/api/documents", files={"file": ("tour.txt", b"Aurora hotel")})
    document = client.get("/api/documents").json()[0]
    client.post(f"/api/documents/{document['id']}/index")
    fake_ollama["error"] = "connection"
    response = client.post("/api/search", json={"query": "Aurora", "mode": mode})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "ollama_unavailable"


def test_index_requires_ready_document_and_valid_identifier(client):
    from uuid import uuid4
    assert client.post(f"/api/documents/{uuid4()}/index").status_code == 404
    assert client.post("/api/documents/invalid-id/index").status_code == 422
    broken = client.post("/api/documents", files={"file": ("bad.pdf", b"broken")}).json()["detail"]["document"]
    assert client.post(f"/api/documents/{broken['id']}/index").status_code == 409


def test_unavailable_ollama_preserves_ready_text(client, fake_ollama):
    fake_ollama["error"] = "connection"
    document = client.post("/api/documents", files={"file": ("trip.txt", b"Aurora hotel")}).json()
    assert client.post(f"/api/documents/{document['id']}/index").status_code == 503
    current = client.get("/api/documents").json()[0]
    assert current["status"] == "ready"
    assert current["embedding_status"] == "error"


@pytest.mark.parametrize("mode", ["vector", "hybrid"])
def test_nonempty_unindexed_corpus_requires_indexing(client, fake_ollama, mode):
    client.post("/api/documents", files={"file": ("trip.txt", b"Aurora hotel")})
    response = client.post("/api/search", json={"query": "Aurora", "mode": mode})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "index_required"
    assert not fake_ollama["requests"]


@pytest.mark.parametrize("mode", ["lexical", "vector", "hybrid"])
def test_empty_corpus_does_not_call_provider(client, fake_ollama, mode):
    response = client.post("/api/search", json={"query": "Aurora", "mode": mode})
    assert response.status_code == 200
    assert response.json()["results"] == []
    assert not fake_ollama["requests"]


def test_provider_failure_preserves_text_and_explicit_retry_works(client, fake_ollama):
    document = client.post("/api/documents", files={"file": ("trip.txt", b"Aurora hotel")}).json()
    fake_ollama["error"] = 429
    response = client.post(f"/api/documents/{document['id']}/index")
    assert response.status_code == 503
    current = client.get("/api/documents").json()[0]
    assert current["status"] == "ready"
    assert current["embedding_status"] == "error"
    assert current["embedding_error"]
    assert client.post("/api/search", json={"query": "Aurora"}).json()["results"]
    fake_ollama["error"] = None
    assert client.post(f"/api/documents/{document['id']}/index").json()["embedding_status"] == "ready"
    # Already-indexed documents do not spend more provider requests.
    fake_ollama["error"] = 500
    assert client.post(f"/api/documents/{document['id']}/index").status_code == 200


def test_partial_index_reports_coverage_and_hybrid_keeps_lexical_hits(client, fake_ollama):
    indexed = client.post("/api/documents", files={"file": ("one.txt", b"Ocean resort")}).json()
    pending = client.post("/api/documents", files={"file": ("two.txt", b"Aurora hotel")}).json()
    client.post(f"/api/documents/{indexed['id']}/index")
    response = client.post("/api/search", json={"query": "Aurora", "mode": "hybrid"})
    assert response.status_code == 200
    body = response.json()
    assert body["indexed_chunks"] == 1
    assert body["total_chunks"] == 2
    assert body["warnings"]
    assert any(hit["document_id"] == pending["id"] for hit in body["results"])


def test_query_provider_failure_does_not_return_lexical_as_hybrid(client, fake_ollama):
    document = client.post("/api/documents", files={"file": ("trip.txt", b"Aurora hotel")}).json()
    client.post(f"/api/documents/{document['id']}/index")
    fake_ollama["error"] = 500
    response = client.post("/api/search", json={"query": "Aurora", "mode": "hybrid"})
    assert response.status_code == 502
    assert "provider-private-secret" not in response.text


@pytest.mark.parametrize("body", [
    {"query": " "}, {"query": "x" * 2001}, {"query": "Hotel", "top_k": 0},
    {"query": "Hotel", "top_k": 21}, {"query": "Hotel", "mode": "unknown"},
    {"query": "Hotel", "unused_option": 1},
])
def test_invalid_search_requests(client, body):
    assert client.post("/api/search", json=body).status_code == 422


def test_top_k_and_deterministic_tie_order(client, fake_ollama):
    for number in range(3):
        document = client.post("/api/documents", files={"file": (f"hotel{number}.txt", f"Aurora hotel {number}".encode())}).json()
        client.post(f"/api/documents/{document['id']}/index")
    request = {"query": "Aurora", "mode": "vector", "top_k": 2}
    first = client.post("/api/search", json=request).json()["results"]
    second = client.post("/api/search", json=request).json()["results"]
    assert len(first) == 2
    assert [hit["chunk_id"] for hit in first] == [hit["chunk_id"] for hit in second]


def test_ready_index_survives_restart(client, fake_ollama):
    from app import db
    document = client.post("/api/documents", files={"file": ("trip.txt", b"Aurora hotel")}).json()
    client.post(f"/api/documents/{document['id']}/index")
    db.initialize()
    response = client.post("/api/search", json={"query": "Aurora", "mode": "vector"})
    assert response.status_code == 200
    assert response.json()["results"][0]["document_id"] == document["id"]


def test_failed_later_batch_never_exposes_partial_index(client, fake_ollama):
    document = client.post("/api/documents", files={"file": ("long.txt", b"Aurora hotel " * 3000)}).json()
    assert document["chunk_count"] > 32
    fake_ollama.update(error=500, error_after=1)
    response = client.post(f"/api/documents/{document['id']}/index")
    assert response.status_code == 502
    current = client.get("/api/documents").json()[0]
    assert current["status"] == "ready"
    assert current["embedding_status"] == "error"
    assert client.post("/api/search", json={"query": "Aurora", "mode": "vector"}).status_code == 409
    assert client.post("/api/search", json={"query": "Aurora", "mode": "lexical"}).json()["results"]
    fake_ollama["error"] = None
    assert client.post(f"/api/documents/{document['id']}/index").json()["embedding_status"] == "ready"


def test_reranking_can_promote_a_candidate_outside_top_k(client, fake_ollama):
    for name in ("first", "second"):
        client.post("/api/documents", files={"file": (name + ".txt", f"Aurora hotel {name}".encode())})
    candidates = client.post("/api/search", json={"query": "Aurora", "top_k": 5}).json()["results"]
    fake_ollama["chat_responses"] = [{"scores": {str(hit["chunk_id"]): index for index, hit in enumerate(candidates)}}]
    response = client.post("/api/search", json={"query": "Aurora", "top_k": 1, "rerank": True})
    assert response.status_code == 200
    assert response.json()["reranked"] is True
    assert response.json()["results"][0]["chunk_id"] == candidates[1]["chunk_id"]


@pytest.mark.parametrize("scores", [{"999999": 3}, {}])
def test_invalid_rerank_ids_never_silently_fall_back(client, fake_ollama, scores):
    for name in ("first", "second"):
        client.post("/api/documents", files={"file": (name + ".txt", f"Aurora hotel {name}".encode())})
    fake_ollama["chat_responses"] = [{"scores": scores}]
    response = client.post("/api/search", json={"query": "Aurora", "rerank": True})
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "invalid_rerank_response"
