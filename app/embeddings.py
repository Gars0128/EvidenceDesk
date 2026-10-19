"""Local Ollama embeddings; no API key or paid provider is required."""

import math
import os

import httpx2 as httpx

from app import config


class EmbeddingError(Exception):
    def __init__(self, code: str, message: str, status: int = 502):
        super().__init__(message)
        self.code = code
        self.status = status


def embed_texts(texts: list[str], *, query: bool = False) -> list[list[float]]:
    if not texts:
        return []
    url = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    prefix = "task: search result | query: " if query else "title: none | text: "
    vectors = []
    try:
        with httpx.Client(timeout=60.0, trust_env=False) as client:
            for start in range(0, len(texts), 32):
                batch = texts[start:start + 32]
                response = client.post(url + "/api/embed", json={
                    "model": config.EMBEDDING_MODEL,
                    "input": [prefix + text for text in batch],
                    "dimensions": config.EMBEDDING_DIMENSIONS,
                    "truncate": False,
                })
                if response.status_code == 404:
                    raise EmbeddingError("embedding_model_missing", "Pull embeddinggemma:300m in Ollama before indexing documents.", 503)
                if response.status_code == 429:
                    raise EmbeddingError("embedding_rate_limit", "Ollama is busy. Please retry.", 503)
                response.raise_for_status()
                body = response.json()
                rows = body["embeddings"]
                if body["model"] != config.EMBEDDING_MODEL or len(rows) != len(batch):
                    raise ValueError("Unexpected model or embedding count")
                for vector in rows:
                    if (not isinstance(vector, list) or len(vector) != config.EMBEDDING_DIMENSIONS
                            or not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                                       and math.isfinite(v) and abs(v) <= 3.402823e38 for v in vector)
                            or not any(vector)):
                        raise ValueError("Invalid embedding vector")
                    vectors.append(vector)
    except httpx.TimeoutException:
        raise EmbeddingError("embedding_timeout", "Ollama timed out. Please retry after the model has loaded.", 504) from None
    except httpx.ConnectError:
        raise EmbeddingError("ollama_unavailable", "Cannot connect to Ollama. Start the Ollama service and check OLLAMA_URL.", 503) from None
    except httpx.HTTPError:
        raise EmbeddingError("embedding_provider_error", "The Ollama embedding request failed. Check its server logs.") from None
    except (ValueError, TypeError, KeyError, AttributeError):
        raise EmbeddingError("invalid_embedding_response", "Ollama returned an invalid embedding response.") from None
    return vectors
