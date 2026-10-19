# Answers and evidence checks

`POST /api/ask` accepts the search fields (`query`, `mode`, `top_k`, `rerank`).
For answers, `top_k` is limited to 1..8 to bound the local model's context. Default
mode is lexical at the API level; the UI defaults to hybrid. Both answer generation
and optional reranking use `qwen3:1.7b` through local Ollama, without API keys.

```json
{
  "query": "Which hotel offers free cancellation?",
  "mode": "hybrid",
  "top_k": 3,
  "rerank": false
}
```

## Response

- `answer`: a concatenation of the returned supported claims, with no extra
  uncited model-written introduction or conclusion.
- `abstained`: true when no supported answer was produced.
- `claims`: claim text and citations. Each citation includes the database chunk
  ID, document UUID/name, page number, and original quotation.
- `retrieval`: source fragments, retrieval coverage, mode, and search latency.
- `warnings`: omitted claims and incomplete semantic index coverage.
- `model`, `elapsed_ms`, and `evidence_check`: configured model, end-to-end handler
  time, and the evidence-checking method used by the pipeline.

The abstention message is Russian for a Cyrillic question and English otherwise.
A missing model, timeout, or invalid structured model output returns an explicit
503/504/502 error; a service failure is not misrepresented as an unanswerable question.

## Evidence pipeline

1. Retrieve page-aware chunks using the selected mode and optional reranking.
2. Ask the chat model for short claims, each with a source chunk ID and quotation.
   Documents and questions are explicitly treated as untrusted data, not instructions.
3. Reject a claim if any of its source IDs are outside the supplied context or a
   quotation does not occur in that source. Whitespace differences are tolerated,
   but the returned quote is the actual original text span and must be a complete
   sentence. This prevents a document heading from being presented as an answer.
4. Omit invalid claims. If none remain, abstain. An empty retrieval result
   abstains immediately without a chat call.

The response never trusts model-supplied document names or page numbers: those
are derived from the retrieved database rows.

## What the checks do not prove

Quotation matching checks provenance, not entailment. The local model can still
select a relevant-looking but incomplete sentence, omit a condition, or return an
incomplete answer. Read source quotations before relying on the result.

Prompt instructions reduce injection risk but are not a proof of isolation from
malicious document text. The model has no application tools, shell access, or
write permissions; model output is only parsed as bounded data. The UI inserts
text with DOM `textContent`, not HTML, so document/model strings do not execute.

The source files themselves are not retained: citations refer to extracted text
and original page numbers, not a downloadable original PDF. There is no OCR,
authentication, or public hosting in this local single-user MVP.

## Local model and performance

```powershell
docker compose exec ollama ollama pull qwen3:1.7b
```

`CHAT_MODEL` can be changed through `.env` for Compose or the Python environment.
Recreate the API after changing it. Generation uses deterministic settings
(`temperature=0`, seed 42), an 8,192-token context, disabled thinking, and bounded
output lengths. Requests have a 120-second timeout.

CPU generation takes much longer than retrieval; cold and queued requests can be
slower. The UI shows an in-progress state rather than assuming an immediate reply.
The Compose configuration pins the tested Ollama image, limits its container to
5 GiB, and caps llama.cpp's host prompt cache with `LLAMA_ARG_CACHE_RAM=256`.
The cache limit was verified in runner logs. Without it, repeated differing
prompts grew RAM usage enough to disrupt Docker on the tested 16 GB host.
This knob is inherited from llama.cpp, not an API-level context-length limit.
Do not run multiple API instances against one database: ingestion restart recovery
still assumes a single process.

## Reranking

`rerank=true` on search or ask fetches at least ten candidates when available.
At most the first ten candidates are scored by the chat model; any remaining
results keep their original order. The model sees at most 1,000 characters per
candidate. A request-specific JSON schema requires a relevance score from 0 to 3
for each actual candidate ID. The server validates every ID and score, then sorts
descending. Ties preserve the base order.

Reranking changes order, not source text or base retrieval scores. `rerank_rank`
is exposed in results. It is optional, adds latency, and may reduce quality. Invalid
rankings return an error instead of silently falling back. Improvements are judged
only from the measured evaluation results.

## Browser workflow

Open http://localhost:8000. Upload one or more PDF/TXT files; the default checkbox
also indexes successful uploads for semantic search. Failed files remain visible
with readable errors, and another file can still be uploaded. Pending/failed indexes
have a preparation/retry button. Duplicate uploads are reported explicitly.

Ask a question or inspect retrieval alone. Search options select mode, top_k, and
reranking. Each claim's source can be expanded to read its quotation; the retrieved
fragments panel shows the full selected chunks. The layout adapts to mobile widths.

References: [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs),
[chat API](https://docs.ollama.com/api/chat), [Qwen3 model](https://ollama.com/library/qwen3:1.7b).
