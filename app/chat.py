"""Bounded, schema-constrained calls to the same local Ollama server."""

import os
from typing import TypeVar

import httpx2 as httpx
from pydantic import BaseModel, ValidationError

from app import config

T = TypeVar("T", bound=BaseModel)


class ChatError(Exception):
    def __init__(self, code: str, message: str, status: int = 502):
        super().__init__(message)
        self.code = code
        self.status = status


def structured_chat(system: str, payload: str, schema: type[T], max_tokens: int = 600, *, output_schema: dict | None = None) -> T:
    url = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    try:
        with httpx.Client(timeout=120.0, trust_env=False) as client:
            response = client.post(url + "/api/chat", json={
                "model": config.CHAT_MODEL, "stream": False, "think": False,
                "format": output_schema or schema.model_json_schema(),
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": payload}],
                "options": {"temperature": 0, "seed": 42, "num_ctx": 8192, "num_predict": max_tokens},
            })
            if response.status_code == 404:
                raise ChatError("chat_model_missing", f"Pull {config.CHAT_MODEL} in Ollama before generating answers or reranking.", 503)
            response.raise_for_status()
            body = response.json()
            if body.get("model") != config.CHAT_MODEL:
                raise ChatError("invalid_chat_response", "Ollama returned a response from an unexpected model.")
            if body.get("done") is not True or body.get("done_reason") == "length":
                raise ChatError("incomplete_model_response", "The model response was incomplete. Try a more specific question.")
            return schema.model_validate_json(body["message"]["content"])
    except httpx.TimeoutException:
        raise ChatError("chat_timeout", "The local chat model timed out. Please retry after it has loaded.", 504) from None
    except httpx.ConnectError:
        raise ChatError("ollama_unavailable", "Cannot connect to Ollama. Start the Ollama service.", 503) from None
    except httpx.HTTPError:
        raise ChatError("chat_provider_error", "The local chat request failed. Check Ollama logs.") from None
    except (ValidationError, ValueError, TypeError, KeyError, AttributeError):
        raise ChatError("invalid_chat_response", "The local model returned an invalid structured response.") from None
