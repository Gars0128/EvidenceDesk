"""Answers consist exclusively of claims with checked source quotations."""

from time import perf_counter

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app import answers, config
from app.search_api import SearchRequest, SearchResponse, search_documents

router = APIRouter(prefix="/api/ask", tags=["answers"])


class AskRequest(SearchRequest):
    top_k: int = Field(default=5, ge=1, le=8)


class AskResponse(BaseModel):
    answer: str
    abstained: bool
    claims: list[answers.AnswerClaim]
    retrieval: SearchResponse
    warnings: list[str]
    model: str
    elapsed_ms: float
    evidence_check: str = "exact_sentence_and_quotation_match"


@router.post("", response_model=AskResponse, responses={
    409: {"description": "Index documents before vector/hybrid retrieval"},
    502: {"description": "Invalid or failed model response"},
    503: {"description": "Model, Ollama, or database unavailable"},
    504: {"description": "Local model timeout"},
})
def ask_documents(request: AskRequest):
    start = perf_counter()
    retrieval = search_documents(request)
    claims, warnings = answers.generate_answer(request.query, [hit.model_dump() for hit in retrieval.results])
    return AskResponse(
        answer="\n".join(claim.text for claim in claims) if claims else answers.no_answer(request.query),
        abstained=not claims, claims=claims, retrieval=retrieval,
        warnings=list(dict.fromkeys(retrieval.warnings + warnings)), model=config.CHAT_MODEL,
        elapsed_ms=(perf_counter() - start) * 1000,
    )
