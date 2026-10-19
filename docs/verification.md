# Verification record — October 19, 2026

## Automated checks

The suite covers public API behavior, parser units, and a dedicated PostgreSQL
test database. Unit API tests use database doubles; integration tests use real
SQL with only the external Ollama HTTP boundary replaced. Tests cover:

- Health and startup failure; database outages without credential disclosure.
- TXT/BOM/Unicode, PDF pages, empty/corrupt/encrypted/no-text files, byte/page/text
  limits, exact duplicates, concurrent duplicates, pagination, restart recovery,
  transaction rollback, and cascade cleanup.
- Russian stemming, exact names, no-match/empty retrieval, cosine ordering, RRF
  deduplication, coverage warnings, provider failures, atomic batch indexing, retry,
  stable ties, and strict request validation.
- Answer/source-page linkage, fabricated IDs/quotes, original whitespace spans,
  cross-document claims, semantic review rejecting a claim despite a real quote,
  empty retrieval, abstention, missing/failed/timed-out models, invalid structured
  output, truncated generation, and context bounds.
- Candidate promotion by reranking, invalid reranking IDs, static UI assets, and
  30-question dataset labels pointing to real evidence.

JavaScript syntax is checked with `node --check app/static/app.js`; Python dependency
consistency is checked with `python -m pip check`.

## Real browser checks

`scripts/check_ui.py` launches headless Microsoft Edge against an isolated UI
instance on port 8001 with the `evidencedesk_ui_test` database. It uses synthetic
travel documents, never a personal corpus. It checks real upload, local indexing,
retrieval, generated answers, expandable citations, and 390-pixel mobile layout.
It also checks corrupt-upload feedback and that model/document HTML-like strings
render as text instead of executing. Browser console errors are treated as failures.

Desktop and mobile screenshots were visually inspected:

- [Desktop](images/ui-desktop.png)
- [Mobile](images/ui-mobile.png)

To repeat, create a disposable database and start an isolated instance in one
PowerShell terminal (development dependencies must already be installed):

```powershell
docker compose exec db createdb -U evidencedesk evidencedesk_ui_test
$env:DATABASE_URL = "postgresql://evidencedesk:evidencedesk_local@127.0.0.1:55432/evidencedesk_ui_test"
$env:OLLAMA_URL = "http://127.0.0.1:11434"
.\.venv\Scripts\python -m uvicorn app.main:app --port 8001
```

Skip database creation if it already exists. In another terminal:

```powershell
.\.venv\Scripts\python scripts/check_ui.py --base-url http://127.0.0.1:8001
```

The script uses the installed `msedge` channel by default. On systems without it,
install Playwright Chromium with `python -m playwright install chromium` and use
`--channel chromium`. It adds demo/error records only to the chosen UI instance;
use a fresh disposable database for clean screenshots.

## Clean-start Docker check

Verified a separate Compose project named `evidencedesk_clean` with a new database
volume and non-default ports. Checked initial migrations, empty document listing,
health HTTP 200, successful TXT upload, lexical retrieval, and the root HTML page.
Removed only that temporary project's containers/network/volume afterward. Main
database and model volumes were preserved.

The actual downloaded embedding/chat models were tested separately through the
main local setup and the isolated evaluation. A healthy server alone is not model
availability; both model pulls in the README are required.

## Hardware and memory observations

Windows host: 16 GB RAM. Docker memory budget observed: 7.67 GiB. CPU-only Ollama
initially accumulated a large host prompt cache during repeated differing prompts.
The final Compose configuration pins Ollama 0.40.6 by image digest, sets
`LLAMA_ARG_CACHE_RAM=256`, uses one parallel model request, allows two loaded models,
and limits the container to 5 GiB. Runner logs confirmed the 256 MiB cache cap;
observed active memory after applying it was about 3.15 GiB.

This protects the local Docker setup from the observed cache growth; it is not a
guarantee that arbitrary larger models will fit. Cache control is inherited from
[llama.cpp's argument parser](https://github.com/ggml-org/llama.cpp/blob/master/common/arg.cpp).

## Quality evaluation

See [the measured report](../evaluation/results/report.md),
[full responses](../evaluation/results/results.json), and
[manual evidence review](../evaluation/results/manual-review.md). Retrieval source
coverage, quotation validity, answerability, and semantic support are different
checks. Small-corpus results and individual timings must not be treated as general
quality or performance guarantees.
