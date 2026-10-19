# EvidenceDesk

Answers about travel documents with verifiable document names, pages, and quotations.
See [PLAN.md](PLAN.md) for the incremental implementation plan.

**Current stage: ingestion and retrieval.** Upload PDF/TXT files and compare
lexical, vector, and hybrid search with document/page sources. Embeddings run
locally through Ollama; no paid API key is needed. Answers and the UI come later.

See [the ingestion guide](docs/ingestion.md) for API examples, limits, architecture,
and the test report.
See [the search guide](docs/search.md) for model setup and retrieval examples.

## Docker quick start

Install Docker with Compose v2 and start the engine. On Windows, Docker Desktop
must use Linux containers. From the repository root in PowerShell:

```powershell
Copy-Item .env.example .env
docker compose up --build -d --wait
docker compose exec ollama ollama pull embeddinggemma:300m
```

On macOS/Linux use `cp .env.example .env` for the first command.

- API documentation: http://localhost:8000/docs
- Readiness endpoint: http://localhost:8000/api/health

Expected HTTP 200 response:

```json
{"status":"ok","database":"ok"}
```

The API initializes the vector extension and applies pending SQL migrations on startup. Compose
waits for database readiness before starting the API. Health checks the live
connection, vector extension, and schema version; a database outage returns 503.
Schema initialization failure prevents API startup.

Database data and Ollama models persist in separate named Docker volumes.
Published ports bind only to localhost.
PostgreSQL is exposed on port 55432 to avoid common local port conflicts.
Example credentials are for local development; this unauthenticated setup is
intended for local use.

```powershell
docker compose ps
docker compose logs api db
docker compose down
```

Stopping containers preserves data. `docker compose down --volumes` also
**deletes the project's database data and downloaded models**; use it only for an intentional reset.

## Local Python development

Use Python 3.13. Start PostgreSQL with Docker and run the API locally:

```powershell
Copy-Item .env.example .env
docker compose up -d --wait db ollama
docker compose exec ollama ollama pull embeddinggemma:300m
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
$env:PGHOST = "127.0.0.1"
$env:PGPORT = "55432"
$env:PGDATABASE = "evidencedesk"
$env:PGUSER = "evidencedesk"
$env:PGPASSWORD = "evidencedesk_local"
.\.venv\Scripts\python -m uvicorn app.main:app --reload
```

Match PG variables to `.env` if you changed its defaults. Compose reads `.env`
automatically; local Python does not. An optional `DATABASE_URL` connection string
overrides the PG connection parameters.

On macOS/Linux use `.venv/bin/python` and `export NAME=value` for environment variables.

## Verification

Install development requirements, then run database-independent unit tests:

```powershell
.\.venv\Scripts\python -m pytest -q
```

The default run covers health, parsing, chunking, validation, duplicates, and API
error handling. Database calls are mocked; six PostgreSQL integration tests are
skipped unless explicitly enabled. See [the ingestion guide](docs/ingestion.md#tests)
for running the full suite against an isolated database.

Actual database smoke check:

```powershell
docker compose up --build -d --wait
Invoke-RestMethod http://localhost:8000/api/health
docker compose exec db psql -U evidencedesk -d evidencedesk -c "SELECT extversion FROM pg_extension WHERE extname = 'vector'; SELECT * FROM schema_version;"
```

Adjust the database username/name in the last command if you changed the defaults.

## Verification history

### Step 1 verification record

Verified on October 19, 2026 with Python 3.13 and Docker:

- Four unit tests passed; dependency checks passed.
- Both Compose services became healthy after a successful image build.
- Live health and OpenAPI requests succeeded; pgvector 0.8.7 and schema version 1 were present.
- API restart succeeded with the existing schema.
- Stopping the project database returned HTTP 503; restarting it restored HTTP 200.

## Project files

```text
app/main.py       FastAPI application and readiness endpoint
app/document_api.py  Upload/list endpoints and response models
app/documents.py   Document, page, and chunk persistence
app/ingestion.py   Filename checks, PDF/TXT extraction, and chunking
app/config.py      Configurable ingestion limits
app/embeddings.py  Local Ollama embedding requests and validation
app/search.py      Lexical, cosine, hybrid retrieval and explicit indexing
app/search_api.py  Search request/response contract
app/db.py          Connections, migrations, and interrupted-job recovery
app/schema.sql     Baseline schema
app/migrations/    Versioned SQL changes
compose.yaml      API and PostgreSQL services
tests/            Unit, API, and real PostgreSQL tests
docs/ingestion.md  Ingestion contract and verification report
docs/search.md     Local model setup and retrieval verification
PLAN.md           Implementation steps
```

## Troubleshooting

- Docker connection errors: start Docker Desktop and check `docker info`.
- Port already allocated: change `APP_PORT` or `DB_PORT` in `.env`. For example,
  `APP_PORT=8001` exposes the API at http://localhost:8001/docs.
- Unhealthy API: inspect `docker compose logs api db`.
- Changing credentials in `.env` does not update an existing PostgreSQL volume.
  Keep the original credentials or intentionally reset disposable data.
- Code and migration changes require rebuilding and restarting the API. Add new
  numbered SQL migrations to `app/db.py`; do not edit migrations already applied
  to an existing database.

## Implementation references

- [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/)
- [Compose startup order](https://docs.docker.com/compose/how-tos/startup-order/)
- [Psycopg connections](https://www.psycopg.org/psycopg3/docs/api/connections.html)
- [pgvector](https://github.com/pgvector/pgvector)
