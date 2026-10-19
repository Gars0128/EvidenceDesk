# EvidenceDesk

Ask questions about uploaded PDF/TXT documents and inspect the document, page,
and exact quotation behind every returned claim. Runs locally with FastAPI,
PostgreSQL + pgvector, and Ollama. No paid API key is required.

![EvidenceDesk desktop interface](docs/images/ui-desktop.png)

## Quick start

Requirements: Docker with Compose v2, Linux containers, internet for initial model
pulls, and enough disk space for Docker images plus about 2 GB of model downloads.
The CPU configuration was tested on Windows with 16 GB host RAM and about 8 GB
available to Docker. The Ollama container is limited to 5 GiB; its separate prompt
cache is limited to 256 MiB to avoid memory growth during repeated model calls.
A GPU is optional.

From the repository root in PowerShell:

```powershell
Copy-Item .env.example .env
docker compose up --build -d --wait
docker compose exec ollama ollama pull embeddinggemma:300m
docker compose exec ollama ollama pull qwen3:1.7b
```

On macOS/Linux use `cp .env.example .env` for the first command. Keep an existing
`.env` when upgrading instead of overwriting your settings.

Open **http://localhost:8000**. API documentation is at **/docs**, and database
readiness is at **/api/health**. Model downloads are a separate first-time step:
a healthy Ollama server does not mean both models have been pulled.

## Five-minute demo

1. Upload `evaluation/corpus/aurora_hotel.txt` and `borealis_hotel.txt` using the UI.
   Leave automatic semantic preparation enabled.
2. Ask: `Compare airport shuttle prices at Aurora Hotel and Borealis Hotel.`
3. Expand a citation to read the exact source quotation and page.
4. Open **Search options** and use **Inspect search results** to compare lexical,
   vector, and hybrid modes. Reranking is optional and adds a chat-model call.
5. Ask: `What is Aurora Hotel's Wi-Fi password?` The documents do not contain it;
   the service should abstain. Inspect the measured evaluation for actual failures,
   not just this intended behavior.

CPU generation can take tens of seconds, especially for cold or queued requests.
Search alone is much faster. The UI shows progress, errors, and pending indexes.

## Features and boundaries

- PDF text-layer extraction and UTF-8 TXT ingestion, page-aware chunks, persistent
  statuses/errors, SHA-256 duplicates, atomic writes, and interrupted-job recovery.
- PostgreSQL full-text retrieval with Russian/English stemming; exact pgvector
  cosine search; hybrid reciprocal rank fusion.
- Local `embeddinggemma:300m` embeddings (768 dimensions) and `qwen3:1.7b` chat.
- Structured answer claims with server-checked source IDs, exact quotations, and
  complete-sentence evidence.
- A responsive, dependency-free browser UI and optional model-based reranking.
- Thirty labelled synthetic questions, six retrieval comparisons, answer evaluation,
  saved actual responses, and a separate evidence-support review.

**Source matching does not prove an answer is correct.** The same small local
model can select an incomplete source sentence or omit conditions.
Read the quotations. Scores are not confidence probabilities. The measured report
records limitations; hybrid/reranking gains are not assumed.

This is a local, single-user MVP. No authentication, OCR, public hosting, queue,
chat history, or original-file storage is included. Citations refer to extracted
text and original page numbers. Only PDF/TXT metadata and text persist.

## API

| Method | Endpoint | Purpose |
| --- | --- | --- |
| POST | `/api/documents` | Upload one PDF/TXT file |
| GET | `/api/documents` | List statuses/counts with limit/offset |
| POST | `/api/documents/{document_id}/index` | Prepare/retry semantic indexing |
| POST | `/api/search` | Retrieve source fragments |
| POST | `/api/ask` | Return supported claims and citations, or abstain |
| GET | `/api/health` | Check PostgreSQL, pgvector, and schema readiness |

Search/ask body:

```json
{
  "query": "Which hotel offers free cancellation?",
  "mode": "hybrid",
  "top_k": 3,
  "rerank": false
}
```

`mode`: lexical/vector/hybrid. API default is lexical; UI default is hybrid.
`top_k`: 1..20 for search, 1..8 for ask. Queries are trimmed and limited to 2,000
characters. Uploads default to 10 MiB, 300 PDF pages, and 2 million extracted
characters. PDFs must have a text layer; encrypted and unreadable PDFs receive
persistent errors. TXT accepts UTF-8 including BOM.

See [ingestion](docs/ingestion.md), [retrieval](docs/search.md), and
[answers/evidence](docs/answers.md) for full behavior, errors, and limitations.

## Tests

Use Python 3.13. Install development dependencies in a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m pytest -q -p no:cacheprovider
```

Default tests do not need Docker or model inference. PostgreSQL integration tests
are explicitly skipped unless enabled. To run all automated tests, create a
separate test database once (skip `createdb` if it already exists):

```powershell
docker compose exec db createdb -U evidencedesk evidencedesk_ingestion_test
$env:TEST_DATABASE_URL = "postgresql://evidencedesk:evidencedesk_local@127.0.0.1:55432/evidencedesk_ingestion_test"
.\.venv\Scripts\python -m pytest -q --integration -p no:cacheprovider
```

Adjust credentials/port to your `.env`. Tests clear only the explicitly configured
`*_test` database and replace only the external Ollama HTTP boundary. They never
need your personal corpus. Browser smoke instructions and verification evidence
are in [docs/verification.md](docs/verification.md).

## Measured evaluation

```powershell
docker compose exec db createdb -U evidencedesk evidencedesk_eval
$env:EVALUATION_DATABASE_URL = "postgresql://evidencedesk:evidencedesk_local@127.0.0.1:55432/evidencedesk_eval"
.\.venv\Scripts\python -m evaluation.run --answers
```

The evaluation clears/reseeds that disposable `*_eval` database. It uses real local
models, so it takes longer than automated tests. Do not point it at data you want
kept. See [protocol](evaluation/README.md), [measured report](evaluation/results/report.md),
[raw results](evaluation/results/results.json), and [manual evidence review](evaluation/results/manual-review.md).

### Targeted answer check — October 19, 2026

The checked configuration is qwen3:1.7b, hybrid retrieval, top_k 3, and reranking
off. Two direct-answer cases returned complete source-backed sentences after the
generation prompt change. A five-question check also exposed that the model may
paraphrase a claim while returning the exact supporting sentence. Validation now
accepts that pattern but still requires a quoted complete source sentence; the
regression test covers a document heading being rejected. The final relaxation was
not sent through another model request in order to keep the targeted check bounded.
Read citations before relying on an answer; the local small model can still omit
one side of a comparison.

## Local Python development

Start PostgreSQL and Ollama in Docker, then run the API locally:

```powershell
docker compose up -d --wait db ollama
$env:PGHOST = "127.0.0.1"
$env:PGPORT = "55432"
$env:PGDATABASE = "evidencedesk"
$env:PGUSER = "evidencedesk"
$env:PGPASSWORD = "evidencedesk_local"
$env:OLLAMA_URL = "http://127.0.0.1:11434"
.\.venv\Scripts\python -m uvicorn app.main:app --reload
```

Match PG variables to `.env`. Compose reads `.env` automatically; local Python
reads process environment variables, not `.env`. `DATABASE_URL` is an optional
connection-string override. On macOS/Linux use `.venv/bin/python` and
`export NAME=value` instead of PowerShell syntax.

## Structure

```text
app/main.py          Application, routes, static UI, and error handlers
app/document_api.py  Upload/list/index endpoints
app/documents.py     Document, page, and chunk persistence
app/ingestion.py     PDF/TXT parsing and chunking
app/embeddings.py    Local embedding requests and validation
app/search.py        Lexical, vector, hybrid queries and indexing
app/search_api.py    Retrieval contract
app/chat.py          Bounded structured Ollama calls
app/answers.py       Claim generation and quote matching
app/ask_api.py       Answer endpoint
app/reranking.py     Bounded candidate scoring
app/db.py            Connections, migrations, restart recovery
app/migrations/      Versioned SQL changes
app/static/          HTML, CSS, and browser JavaScript
scripts/check_ui.py  Real browser smoke checks
evaluation/          Synthetic corpus, 30 questions, runner, and results
tests/               Unit/API/PostgreSQL tests
```

## Operations and troubleshooting

```powershell
docker compose ps
docker compose logs --tail 50 api db ollama
docker compose exec ollama ollama list
docker compose down
```

Stopping containers preserves database/model volumes. `docker compose down
--volumes` **deletes database data and downloaded models**; use only for an
intentional reset. Migrations run once on API startup and preserve existing text.

- Model missing: pull the exact embedding/chat tags from Quick start.
- Port occupied: change `APP_PORT`, `DB_PORT`, or `OLLAMA_PORT` in `.env` and recreate
  services. For native Python, update its connection URLs as well.
- Unindexed documents: click **Prepare semantic search** or call the index endpoint.
- Slow CPU inference: allow a cold start, keep reranking off for routine questions,
  and inspect Docker memory. The pinned Ollama configuration caps its prompt cache
  and memory; arbitrary larger models may not fit that budget.
- Docker API failing after memory pressure: stop model workload first. Do not reset
  or delete database volumes to fix a model-memory issue.
- Credential changes do not update existing PostgreSQL volumes. Keep original
  credentials or intentionally reset disposable data.
- Code changes require rebuilding/restarting the API. Add new numbered migrations;
  do not edit SQL migrations already applied to an existing database.
- Run one API process per database: startup recovery marks incomplete ingestion
  records as errors. Multiple replicas/worker queues are outside this MVP.

Original development plan: [PLAN.md](PLAN.md). Documentation and code comments are
in English. Git commits and pushes are performed by the project owner.
