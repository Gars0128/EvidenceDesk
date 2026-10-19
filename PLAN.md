# EvidenceDesk — MVP implementation plan

A small application for answering questions about uploaded travel documents.
The goal is a working end-to-end flow with minimal infrastructure.

## Scope

- Python, FastAPI, PostgreSQL + pgvector, Docker Compose.
- Plain HTML/CSS/JavaScript UI without a separate frontend framework.
- Text-based PDFs and UTF-8 TXT; no OCR in the first version.
- One provider: OpenAI for embeddings and generation, configured through environment variables.
- Without an API key, ingestion and lexical search work. Semantic search and generation return clear configuration errors, not simulated results.
- Synchronous ingestion initially; no queue or worker.
- Preserve PDF page numbers; TXT uses page 1.
- Local, single-user use. Public deployment and authentication are outside the MVP.

## Commit-sized steps

### 0. `docs: record MVP implementation plan`

Record scope and acceptance criteria before coding.

### 1. `chore: bootstrap FastAPI and PostgreSQL`

Status: completed and verified on October 19, 2026.

Application structure, dependencies, Dockerfile, Compose, `.env.example`, `.gitignore`,
PostgreSQL with vector extension and initial schema, database readiness endpoint,
and README startup instructions.

Acceptance: application and database start; health reports readiness.

### 2. `feat: ingest PDF and TXT with source pages`

Implement `POST /api/documents` and `GET /api/documents`. Enforce file size and
format limits and safe filenames. Store documents, pages, chunks, and
processing/ready/error states. Detect duplicates using SHA-256 and report them
explicitly. Persist corrupt-PDF errors without breaking other requests. Explain
when a PDF has no extractable text layer.

Acceptance: test TXT, multipage PDF, corrupt files, duplicates, and page numbers.

### 3. `feat: add lexical vector and hybrid retrieval`

Implement `POST /api/search` with query, mode, and top_k. Use PostgreSQL full-text
search for Russian/English text, embeddings with pgvector cosine search, and
reciprocal rank fusion for hybrid retrieval. Fix the embedding model and dimensions
in configuration. Preserve extracted text on provider failures and allow explicit
reindexing. Return chunk ID, document, page, text, and score.

Acceptance: exact names, semantic queries, empty database, missing key, and provider failures.

### 4. `feat: answer questions with validated citations`

Implement `POST /api/ask` with retrieved context and structured claims referencing
chunk IDs. Include document, page, and exact quotation. Validate that source IDs
belong to the supplied context and quotations occur in those sources. Abstain when
evidence is insufficient: "No answer was found in the uploaded documents."
Treat document contents as data, not model instructions. Citation ID and quotation
checks do not prove semantic support for a claim.

Acceptance: answerable, unanswerable, cross-document questions, and fabricated source IDs.

### 5. `feat: add simple document and question UI`

Three areas: documents, question, answer with sources. Add upload statuses, clear
errors, loading feedback, expandable citations, and advanced controls for search
mode, top_k, and retrieved chunks.

Acceptance: complete the full flow in a browser, including errors.

### 6. `feat: add optional reranking and retrieval evaluation`

Optional candidate reranking through the same LLM provider. Add demo documents and
30 labelled questions: ordinary, exact-name, cross-document, and unanswerable.
Compare lexical/vector/hybrid with and without reranking. Report recall@k,
latency, abstention accuracy, and failures. Separately review whether cited evidence
supports answer claims. Record real measurements without assuming improvements.

Acceptance: repeatable evaluation with parameters and measurement dates.

### 7. `docs: finish setup guide and demo walkthrough`

Verify clean-environment startup using the README. Document API key setup,
limitations, external API costs, and troubleshooting. Include a short demo and
measured quality report.

Acceptance: a new user can start the app and complete the demo without reading code.

## Working agreement

One step at a time: implement, run appropriate checks, make a small commit, report results.
Keep documentation in English. Do not add LangChain, OCR, queues, a separate
frontend, or authentication without a concrete need.
