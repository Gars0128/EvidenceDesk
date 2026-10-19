"""Search request validation and page-aware retrieval responses."""

from time import perf_counter
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app import embeddings, search

router = APIRouter(prefix="/api/search", tags=["search"])


class SearchRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    query: str = Field(min_length=1, max_length=2000)
    mode: Literal["lexical", "vector", "hybrid"] = "lexical"
    top_k: int = Field(default=5, ge=1, le=20)


class SearchHit(BaseModel):
    chunk_id: int
    document_id: UUID
    filename: str
    page_number: int
    chunk_index: int
    text: str
    score: float
    lexical_rank: int | None = None
    vector_rank: int | None = None


class SearchResponse(BaseModel):
    mode: str
    results: list[SearchHit]
    elapsed_ms: float
    total_chunks: int
    indexed_chunks: int
    warnings: list[str] = Field(default_factory=list)


@router.post("", response_model=SearchResponse, responses={
    409: {"description": "No indexed chunks; index documents first"},
    502: {"description": "Embedding provider error"},
    503: {"description": "Ollama/model unavailable, busy service, or unavailable database"},
    504: {"description": "Embedding provider timeout"},
})
def search_documents(request: SearchRequest):
    start = perf_counter()
    total, indexed = search.corpus_counts()
    warnings = []
    if request.mode == "lexical":
        results = search.lexical_search(request.query, request.top_k)
    elif total == 0:
        results = []
    else:
        if indexed == 0:
            raise HTTPException(409, detail={"code": "index_required", "message": "Index a ready document before using vector/hybrid search."})
        if indexed < total:
            warnings.append("Some document chunks have no embeddings; semantic search covers only indexed chunks.")
        vector = embeddings.embed_texts([request.query], query=True)[0]
        results = (search.vector_search(vector, request.top_k) if request.mode == "vector"
                   else search.hybrid_search(request.query, vector, request.top_k))
    return SearchResponse(
        mode=request.mode, results=results, elapsed_ms=(perf_counter() - start) * 1000,
        total_chunks=total, indexed_chunks=indexed, warnings=warnings,
    )
