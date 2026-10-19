# EvidenceDesk

Answers about travel documents with verifiable document names, pages, and quotations.
See [PLAN.md](PLAN.md) for the incremental implementation plan.

**Current stage: step 1 — application and database skeleton.** Upload, search,
answers, and the UI come in later steps. No LLM API key is needed yet.

## Docker quick start

Install Docker with Compose v2 and start the engine. On Windows, Docker Desktop
must use Linux containers. From the repository root in PowerShell:

```powershell
Copy-Item .env.example .env
docker compose up --build -d --wait
```

On macOS/Linux use `cp .env.example .env` for the first command.

- API documentation: http://localhost:8000/docs
- Readiness endpoint: http://localhost:8000/api/health

Expected HTTP 200 response:

```json
{"status":"ok","database":"ok"}
```

The API initializes the vector extension and initial schema on startup. Compose
waits for database readiness before starting the API. Health checks the live
connection, vector extension, and schema version; a database outage returns 503.
Schema initialization failure prevents API startup.

Data persists in a named Docker volume. Both ports bind only to localhost.
PostgreSQL is exposed on port 55432 to avoid common local port conflicts.
Example credentials are for local development; this unauthenticated setup is
intended for local use.

```powershell
docker compose ps
docker compose logs api db
docker compose down
```

Stopping containers preserves data. `docker compose down --volumes` also
**deletes the project's database data**; use it only for an intentional reset.

## Local Python development

Use Python 3.13. Start PostgreSQL with Docker and run the API locally:

```powershell
Copy-Item .env.example .env
docker compose up -d --wait db
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

Tests cover healthy readiness, missing schema, database outages without credential
leaks, and startup failure. Database calls are mocked in these tests.

Actual database smoke check:

```powershell
docker compose up --build -d --wait
Invoke-RestMethod http://localhost:8000/api/health
docker compose exec db psql -U evidencedesk -d evidencedesk -c "SELECT extversion FROM pg_extension WHERE extname = 'vector'; SELECT * FROM schema_version;"
```

Adjust the database username/name in the last command if you changed the defaults.

## Structure

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
app/db.py         Connections and initial schema setup
app/schema.sql    Idempotent initial schema
compose.yaml      API and PostgreSQL services
tests/            Readiness and startup tests
PLAN.md           Implementation steps
```

## Troubleshooting

- Docker connection errors: start Docker Desktop and check `docker info`.
- Port already allocated: change `APP_PORT` or `DB_PORT` in `.env`. For example,
  `APP_PORT=8001` exposes the API at http://localhost:8001/docs.
- Unhealthy API: inspect `docker compose logs api db`.
- Changing credentials in `.env` does not update an existing PostgreSQL volume.
  Keep the original credentials or intentionally reset disposable data.
- Schema file edits require rebuilding and restarting the API. This initializer
  covers the first schema only; later changes will need explicit migrations.

## Implementation references

- [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/)
- [Compose startup order](https://docs.docker.com/compose/how-tos/startup-order/)
- [Psycopg connections](https://www.psycopg.org/psycopg3/docs/api/connections.html)
- [pgvector](https://github.com/pgvector/pgvector)
