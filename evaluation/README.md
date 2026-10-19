# Evaluation protocol

The corpus contains eight synthetic English travel documents. `questions.json`
contains 30 labelled questions: eight ordinary, eight with exact names, eight
cross-document, and six unanswerable. Each answerable question identifies expected
document names, page numbers, and evidence substrings. Expected fact regex patterns
are diagnostic aids, not complete semantic answer labels.

The corpus is intentionally small. It exercises different retrieval modes and
failure cases but does not establish performance on arbitrary customer PDFs,
Russian questions, OCR, or large collections. Personal documents are never used
in the report.

## Run

Start Docker services, download both models, and install development dependencies
as described in the main README. Create a dedicated evaluation database once:

```powershell
docker compose exec db createdb -U evidencedesk evidencedesk_eval
$env:EVALUATION_DATABASE_URL = "postgresql://evidencedesk:evidencedesk_local@127.0.0.1:55432/evidencedesk_eval"
.\.venv\Scripts\python -m evaluation.run --answers
```

Adjust credentials/port to your configuration. If the database already exists,
skip `createdb`. The runner refuses database names not ending in `_eval` and
**clears the documents in that explicitly disposable database** before seeding
fixtures. Do not use a database containing anything you want to keep.

For retrieval only, omit `--answers`. A completed retrieval run and its unchanged
evaluation database can be reused to reevaluate answers after changing answer
prompts:

```powershell
.\.venv\Scripts\python -m evaluation.run --answers-only
```

That command preserves the six completed retrieval configurations and replaces
the answer results. It validates model names and top_k against the existing report.
The raw report records separate measurement dates for answer-only reruns.

The evaluation uses real PostgreSQL/pgvector and local Ollama, not mocked embeddings
or generated expected results. Generation can take several minutes on a CPU.

## Measurements

- Six retrieval configurations: lexical/vector/hybrid, with reranking off and on.
- Recall@k: matched expected source/evidence spans divided by expected spans.
- Any-source hit@k: fraction of answerable questions with at least one gold source.
- All-sources@k: fraction with every required source in the top k.
- End-to-end mean, median, and p95 search request latency, including model calls.
- Errors count as misses. Questions without an answer are excluded from retrieval
  recall denominators: nearest-neighbor retrieval alone is not an abstention mechanism.
- Answer evaluation: one fixed configuration (hybrid, no reranking), correct
  abstentions, request errors, exact quotation matches, and diagnostic expected-fact
  coverage. Model-supported answers are not automatically counted as correct.
- Separate manual review examines actual claim support and completeness. Exact
  citation validity and source retrieval are reported separately.

`results/results.json` contains complete responses, parameters, timestamps, and
per-question outcomes. `results/report.md` summarizes measured results and failure
IDs. `results/manual-review.md` records a human-readable evidence audit of selected
answers, including rejected or incomplete ones.

Latencies are observations from local development hardware, not a load test or
service guarantee. Browser tests and other local work may overlap. Model tags,
hardware, caches, and Ollama versions can change results. The report does not assume
hybrid or reranking improves the baseline.
