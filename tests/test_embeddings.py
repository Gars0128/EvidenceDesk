"""Ollama response validation with a fake HTTP boundary."""

import pytest

from app.embeddings import EmbeddingError, embed_texts


def test_batches_preserve_input_order(fake_ollama):
    fake_ollama["vector_for"] = lambda text: [float(int(text.split(" | text: ")[1]) + 1)] + [0.0] * 767
    vectors = embed_texts([str(index) for index in range(35)])
    assert [vector[0] for vector in vectors] == list(range(1, 36))
    assert [len(request["input"]) for request in fake_ollama["requests"]] == [32, 3]
    assert fake_ollama["requests"][0]["dimensions"] == 768
    assert fake_ollama["requests"][0]["truncate"] is False


def test_retrieval_task_prefixes(fake_ollama):
    embed_texts(["Hotel"])
    embed_texts(["Flexible booking"], query=True)
    assert fake_ollama["requests"][0]["input"] == ["title: none | text: Hotel"]
    assert fake_ollama["requests"][1]["input"] == ["task: search result | query: Flexible booking"]


@pytest.mark.parametrize("status,code", [
    (401, "embedding_provider_error"), (429, "embedding_rate_limit"),
    (500, "embedding_provider_error"), (404, "embedding_model_missing"),
    ("connection", "ollama_unavailable"), ("timeout", "embedding_timeout"),
])
def test_provider_errors_do_not_disclose_response_body(fake_ollama, status, code):
    fake_ollama["error"] = status
    with pytest.raises(EmbeddingError) as error:
        embed_texts(["Hotel"])
    assert error.value.code == code
    assert "provider-private-secret" not in str(error.value)


@pytest.mark.parametrize("vector", [[1.0], [0.0] * 768, [True] * 768])
def test_invalid_vectors_are_rejected(fake_ollama, vector):
    fake_ollama["vector_for"] = lambda text: vector
    with pytest.raises(EmbeddingError) as error:
        embed_texts(["Hotel"])
    assert error.value.code == "invalid_embedding_response"


@pytest.mark.parametrize("body", [
    {"model": "wrong", "embeddings": []},
    {"model": "embeddinggemma:300m", "embeddings": []},
    {},
])
def test_invalid_response_shape(fake_ollama, body):
    fake_ollama["override"] = body
    with pytest.raises(EmbeddingError) as error:
        embed_texts(["Hotel"])
    assert error.value.code == "invalid_embedding_response"
