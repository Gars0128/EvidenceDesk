# EvidenceDesk evaluation

Measured: 2026-10-19T11:36:12.462274+00:00

Embedding model: `embeddinggemma:300m`. Chat model: `qwen3:1.7b`. Top k: 3.

Synthetic corpus: eight UTF-8 travel documents; 30 questions (24 answerable, six unanswerable).
All results use real PostgreSQL, pgvector, and local Ollama. No provider responses are mocked.

## Retrieval

Recall counts expected document/page/evidence-span combinations, not merely any hit from the right file.
Unanswerable questions are excluded from recall denominators. Errors count as retrieval misses.

| Configuration | Recall@k | Any-source hit@k | All sources@k | Mean ms | p95 ms | Errors |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| lexical | 21.9% | 29.2% | 25.0% | 29.01 | 49.45 | 0 |
| lexical+rerank | 21.9% | 29.2% | 25.0% | 25.61 | 36.41 | 0 |
| vector | 96.9% | 100.0% | 95.8% | 66.7 | 93.98 | 0 |
| vector+rerank | 96.9% | 100.0% | 95.8% | 7661.09 | 8344.57 | 0 |
| hybrid | 96.9% | 100.0% | 95.8% | 78.02 | 107.6 | 0 |
| hybrid+rerank | 96.9% | 100.0% | 95.8% | 7137.76 | 7876.25 | 0 |

Hybrid and reranking improvements are not assumed. Compare measured values, including added latency.
The tiny corpus and model/hardware configuration limit generalization.

## Retrieval failures

- **lexical:** q01, q02, q03, q04, q05, q08, q12, q13, q15, q16, q17, q18, q19, q20, q21, q22, q23, q24
- **lexical+rerank:** q01, q02, q03, q04, q05, q08, q12, q13, q15, q16, q17, q18, q19, q20, q21, q22, q23, q24
- **vector:** q24
- **vector+rerank:** q24
- **hybrid:** q24
- **hybrid+rerank:** q24

## Answers (hybrid, without reranking)

- Answerable questions receiving an answer: 41.7%.
- Correct abstentions on unanswerable questions: 6/6.
- Request errors: 0/30.
- Exact source-quotation matches: 12/12 citations.
- Mean end-to-end latency: 10689 ms.

An answered question is not necessarily correct. Exact quotes are not proof of claim support.
Expected fact-pattern coverage in the JSON is a diagnostic proxy, not a semantic accuracy score.
See the separate manual evidence review for claim support and completeness.

## Answer failures / omissions

- q01: status 200; fact coverage 0.0; abstained False.
- q02: status 200; fact coverage 0.0; abstained True.
- q03: status 200; fact coverage 0.0; abstained True.
- q04: status 200; fact coverage 0.0; abstained True.
- q06: status 200; fact coverage 0.0; abstained True.
- q07: status 200; fact coverage 0.0; abstained True.
- q08: status 200; fact coverage 0.0; abstained True.
- q09: status 200; fact coverage 0.0; abstained True.
- q10: status 200; fact coverage 0.0; abstained True.
- q13: status 200; fact coverage 0.0; abstained True.
- q14: status 200; fact coverage 0.0; abstained True.
- q16: status 200; fact coverage 0.0; abstained True.
- q17: status 200; fact coverage 0.5; abstained False.
- q18: status 200; fact coverage 0.5; abstained False.
- q19: status 200; fact coverage 0.0; abstained True.
- q21: status 200; fact coverage 0.3333333333333333; abstained False.
- q23: status 200; fact coverage 0.0; abstained True.
- q24: status 200; fact coverage 0.0; abstained True.
