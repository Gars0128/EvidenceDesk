"""Grounded-answer behavior through HTTP with real retrieval and PostgreSQL."""

import pytest
from fastapi.testclient import TestClient

from app.main import app

pytestmark = pytest.mark.integration


@pytest.fixture
def client(postgres):
    with TestClient(app) as client:
        yield client


def test_answer_contains_source_page_and_exact_quote(client, fake_ollama):
    document = client.post("/api/documents", files={"file": ("hotel.txt", b"Aurora offers free cancellation until 48 hours before arrival.")}).json()
    chunk = client.post("/api/search", json={"query": "Aurora"}).json()["results"][0]
    fake_ollama["chat_responses"] = [{"insufficient_evidence": False, "claims": [{
        "text": "Aurora allows free cancellation up to 48 hours before arrival.",
        "citations": [{"chunk_id": chunk["chunk_id"], "quote": chunk["text"]}],
    }]}]
    response = client.post("/api/ask", json={"query": "Aurora", "mode": "lexical"})
    assert response.status_code == 200
    body = response.json()
    assert body["abstained"] is False
    assert "48 hours" in body["answer"]
    source = body["claims"][0]["citations"][0]
    assert source["document_id"] == document["id"]
    assert source["page_number"] == 1
    assert source["quote"] in chunk["text"]


def prepare(client, text=b"Aurora offers free cancellation."):
    client.post("/api/documents", files={"file": ("hotel.txt", text)})
    return client.post("/api/search", json={"query": "Aurora"}).json()["results"][0]


@pytest.mark.parametrize("invalid", ["id", "quote"])
def test_fabricated_citations_are_not_returned(client, fake_ollama, invalid):
    source = prepare(client)
    fake_ollama["chat_responses"] = [{"insufficient_evidence": False, "claims": [{
        "text": "Aurora has free cancellation.", "citations": [{
            "chunk_id": source["chunk_id"] + 999 if invalid == "id" else source["chunk_id"],
            "quote": "Invented quotation" if invalid == "quote" else source["text"],
        }],
    }]}]
    body = client.post("/api/ask", json={"query": "Aurora"}).json()
    assert body["abstained"] is True
    assert body["claims"] == []
    assert body["warnings"]


def test_heading_or_paraphrase_cannot_bypass_exact_sentence_check(client, fake_ollama):
    source = prepare(client)
    fake_ollama["chat_responses"] = [{"insufficient_evidence": False, "claims": [{"text": "Aurora Hotel — family stay",
     "citations": [{"chunk_id": source["chunk_id"], "quote": "Aurora Hotel — family stay"}]}]}]
    body = client.post("/api/ask", json={"query": "Aurora"}).json()
    assert body["abstained"] is True
    assert body["claims"] == []
    assert "citation" in body["warnings"][0]


def test_empty_retrieval_abstains_without_chat_call(client, fake_ollama):
    body = client.post("/api/ask", json={"query": "Какие экскурсии доступны?"}).json()
    assert body["abstained"] is True
    assert body["answer"] == "В загруженных документах ответ не найден."
    assert not fake_ollama["requests"]


def test_model_can_abstain_despite_nearby_fragments(client, fake_ollama):
    prepare(client)
    fake_ollama["chat_responses"] = [{"insufficient_evidence": True, "claims": []}]
    body = client.post("/api/ask", json={"query": "Aurora"}).json()
    assert body["abstained"] is True
    assert body["retrieval"]["results"]


def test_whitespace_matching_returns_original_source_span(client, fake_ollama):
    source = prepare(client, b"Aurora offers free\ncancellation.")
    fake_ollama["chat_responses"] = [{"insufficient_evidence": False, "claims": [{"text": "Cancellation is free.",
     "citations": [{"chunk_id": source["chunk_id"], "quote": "free cancellation"}]}]}]
    body = client.post("/api/ask", json={"query": "Aurora"}).json()
    assert body["abstained"] is True


def test_cross_document_answer_keeps_sources_separate(client, fake_ollama):
    for name, text in [("aurora", b"Aurora hotel permits free cancellation."), ("borealis", b"Borealis hotel is non-refundable.")]:
        client.post("/api/documents", files={"file": (name + ".txt", text)})
    sources = client.post("/api/search", json={"query": "hotel"}).json()["results"]
    fake_ollama["chat_responses"] = [{"insufficient_evidence": False, "claims": [
            {"text": source["text"], "citations": [{"chunk_id": source["chunk_id"], "quote": source["text"]}]}
            for source in sources]}]
    body = client.post("/api/ask", json={"query": "hotel"}).json()
    assert len(body["claims"]) == 2
    assert len({claim["citations"][0]["document_id"] for claim in body["claims"]}) == 2


@pytest.mark.parametrize("error,status,code", [(404, 503, "chat_model_missing"), (500, 502, "chat_provider_error"), ("timeout", 504, "chat_timeout")])
def test_chat_failure_is_explicit(client, fake_ollama, error, status, code):
    prepare(client)
    fake_ollama["error"] = error
    response = client.post("/api/ask", json={"query": "Aurora"})
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code
    assert "provider-private-secret" not in response.text


def test_malformed_model_answer_is_not_presented_as_no_answer(client, fake_ollama):
    prepare(client)
    fake_ollama["chat_responses"] = [{"claims": "wrong type"}]
    response = client.post("/api/ask", json={"query": "Aurora"})
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "invalid_chat_response"


def test_ask_context_limit(client):
    assert client.post("/api/ask", json={"query": "Aurora", "top_k": 9}).status_code == 422


def test_truncated_generation_is_not_accepted(client, fake_ollama):
    prepare(client)
    fake_ollama["override"] = {"model": "qwen3:1.7b", "done": True, "done_reason": "length", "message": {"content": "{}"}}
    response = client.post("/api/ask", json={"query": "Aurora"})
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "incomplete_model_response"
