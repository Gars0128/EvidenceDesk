# Local retrieval with PostgreSQL and Ollama

## Setup

No API key or paid service is required. Ollama runs locally in a third Docker
service, using CPU by default. This avoids a separate Windows installation.

```powershell
docker compose up --build -d --wait
docker compose exec ollama ollama pull embeddinggemma:300m
```

The first run downloads the Ollama image and a model of approximately 622 MB.
Allow several GB of disk space for the image, model, and runtime. Internet is
required for downloading; document embeddings are then computed locally. The
model is stored in the `ollama_data` volume and survives ordinary container stops.

The API connects to `http://ollama:11434` inside Compose. Local Python defaults to
`http://127.0.0.1:11434`; override `OLLAMA_URL` in the Python process if needed.
`OLLAMA_PORT` in `.env` changes the host port, not the internal Docker address.
If you change it, update the local Python `OLLAMA_URL` accordingly.

`GET /api/health` remains a database readiness check. Ollama readiness checks that
its server is reachable; it does not guarantee a particular model is downloaded.
Lexical search and document uploads do not depend on Ollama availability.

## Upload and index

1. Upload a PDF/TXT through `POST /api/documents` in http://localhost:8000/docs.
2. Copy the returned document UUID.
3. Call `POST /api/documents/{document_id}/index` with that UUID.
4. Check that `embedding_status` is `ready` in the response or document list.

PowerShell example:

```powershell
$documentId = "replace-with-document-uuid"
Invoke-RestMethod -Method Post "http://localhost:8000/api/documents/$documentId/index"
```

Indexing is explicit: uploading does not start model inference. Existing documents
can be indexed without uploading again. Indexing an already-ready index is
idempotent. Failed indexing can be retried with the same endpoint.

Document `status` describes text ingestion. The separate `embedding_status` is
`pending`, `ready`, or `error`; `embedding_error` contains a readable failure and
`embedding_model` identifies a successfully indexed model. Model errors preserve
the document's ready text and lexical search availability.

Embeddings are generated in batches of 32 outside database transactions. All
vectors for a document and its index status are then saved atomically. A failed
batch does not leave a partially searchable document index.

## Search

`POST /api/search` accepts:

```json
{
  "query": "Which hotel allows cancellation without a fee?",
  "mode": "hybrid",
  "top_k": 5
}
```

`mode` is `lexical` (default), `vector`, or `hybrid`. `top_k` is 1..20.
Queries are trimmed, must be non-empty, and are limited to 2,000 characters.

PowerShell:

```powershell
$body = @{ query = "free cancellation"; mode = "lexical"; top_k = 5 } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/search -ContentType "application/json; charset=utf-8" -Body ([System.Text.Encoding]::UTF8.GetBytes($body))
```

The response contains:

- `results`: chunk ID, document UUID/name, page number, chunk index, full chunk
  text, and score. Hybrid hits also expose lexical/vector candidate ranks.
- `elapsed_ms`: time spent inside the search handler, including model inference.
- `total_chunks` / `indexed_chunks`: search coverage for ready documents.
- `warnings`: a notice when semantic retrieval covers only part of the corpus.

Only text-ready documents are searched. Empty corpora return an empty result list
without model inference. For a nonempty corpus without any indexed chunks,
vector/hybrid returns HTTP 409 (`index_required`). Partial indexing is allowed with
an explicit warning; hybrid can still include lexical hits from unindexed documents.
There is no silent fallback from hybrid/vector to lexical on a model error.

## How the modes work

**Lexical:** PostgreSQL generated `tsvector` with English, Russian, and simple
configurations; GIN index; `websearch_to_tsquery`; `ts_rank_cd` ranking. The simple
configuration preserves terms including names and stop words. Russian/English
configurations add stemming. Quoted phrases are supported. This is PostgreSQL
full-text ranking, not BM25; long natural-language queries may have no lexical
match because their terms are combined with AND by default.

**Vector:** `embeddinggemma:300m`, 768 dimensions, and pgvector cosine distance.
Queries use `task: search result | query: ...`; document chunks use
`title: none | text: ...`, following the model's retrieval prompt format. Requests
set `truncate=false`, so model-context overflow is reported rather than silently
dropping part of a source. Invalid, non-finite, zero, or wrong-size vectors are rejected.

The model and dimension are fixed in `app/config.py`, matching the SQL schema.
Changing models requires reindexing, even if dimensions happen to match. Migration
005 replaces old OpenAI embeddings with null local-model vectors and resets index
metadata; documents, pages, and chunk text are preserved. This handles databases
that applied the intermediate 1536-dimensional schema during development.

Cosine search is an exact scan for this small corpus. There is no HNSW index yet;
add approximate indexing only when measurements justify it.

**Hybrid:** retrieve up to `max(20, top_k * 4)` candidates per mode and combine
their positions with reciprocal rank fusion: sum `1 / (60 + rank)`. A chunk found
by both methods appears only once. Ties use chunk ID for reproducibility.

Scores across modes have different scales; they are not probabilities. A nearest
neighbor is not proof that a question is answerable. Abstention and answer support
checks belong to the next stage. Hybrid superiority is not assumed or measured yet.

## Errors and troubleshooting

| HTTP | Code | Action |
| --- | --- | --- |
| 404 | `document_not_found` | Check document UUID |
| 409 | `document_not_ready` | Resolve text-ingestion error first |
| 409 | `index_required` | Index a ready document |
| 503 | `ollama_unavailable` | Start Ollama/check its URL |
| 503 | `embedding_model_missing` | Pull `embeddinggemma:300m` |
| 503 | `embedding_rate_limit` | Ollama is busy; retry |
| 504 | `embedding_timeout` | Model request exceeded 60 seconds; retry after loading |
| 502 | `embedding_provider_error` | Inspect Ollama logs; input may exceed model context |
| 502 | `invalid_embedding_response` | Check model identity and response format |

Useful commands:

```powershell
docker compose exec ollama ollama list
docker compose logs --tail 50 ollama api
```

CPU performance depends on your hardware and Docker memory allocation. The first
request can be slower because the model loads into memory. GPU setup is optional
and is not part of this portable CPU configuration. This stage only downloads an
embedding model; a chat model for generating answers comes in the next stage.

## Tests

Use the commands in [the ingestion guide](ingestion.md#tests) for unit and isolated
PostgreSQL integration tests. External HTTP is replaced in automated tests;
SQL, migrations, ranking, indexing, and API validation remain real in integration tests.

The tests cover exact source pages, Russian inflections, empty/no-match queries,
all three modes, RRF deduplication, stable ties, coverage warnings, model failures,
retry, idempotent indexing, and input validation. They verify mechanics with known
vectors, not model quality. Real local-model smoke results are recorded separately.

### Automated verification — October 19, 2026

89 tests passed: 57 database-independent tests and 32 real PostgreSQL integration
tests, with only the Ollama HTTP boundary replaced. Verified that a failed second
embedding batch preserves text and exposes no partial vector index; explicit retry
then succeeds. No paid API calls are made by the tests.

### Real local-model smoke check — October 19, 2026

Ran the complete HTTP flow in Docker with the downloaded `embeddinggemma:300m`
model and real PostgreSQL, without replacing model responses. Uploaded/indexed two
temporary hotel documents: Aurora with free cancellation and Borealis with
non-refundable reservations. All three modes ranked Aurora first and returned
page 1 with the source text:

| Mode | Query | Handler latency |
| --- | --- | --- |
| Lexical | `"Hotel Aurora"` | 15.78 ms |
| Vector | `Can I cancel my booking without paying a fee?` | 44.72 ms |
| Hybrid | `free cancellation` | 45.98 ms |

These are individual warm-model observations on a two-document smoke corpus,
not a quality benchmark or latency guarantee. Temporary smoke records were removed;
the downloaded model and healthy services remain available. The planned 30-question
evaluation is documented separately in [the evaluation protocol](../evaluation/README.md)
and [the measured report](../evaluation/results/report.md).

## References

- [Ollama embedding API](https://docs.ollama.com/api/embed)
- [EmbeddingGemma in Ollama](https://ollama.com/library/embeddinggemma)
- [Model retrieval prompts](https://ai.google.dev/gemma/docs/embeddinggemma/model_card)
- [PostgreSQL full-text controls](https://www.postgresql.org/docs/17/textsearch-controls.html)
- [pgvector](https://github.com/pgvector/pgvector)
