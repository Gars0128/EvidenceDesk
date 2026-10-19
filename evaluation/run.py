"""Evaluate synthetic fixtures in an explicitly disposable *_eval database."""

import argparse
import json
import os
import platform
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

import psycopg
from fastapi.testclient import TestClient

from app import config, db
from app.main import app

ROOT = Path(__file__).resolve().parent


def source_matches(hit, expected):
    return (hit["filename"] == expected["filename"] and hit["page_number"] == expected["page_number"]
            and expected["contains"] in hit["text"])


def percentile(values, fraction):
    if not values:
        return None
    return sorted(values)[max(0, int(len(values) * fraction + 0.9999) - 1)]


def summarize(rows):
    answerable = [row for row in rows if row["expected_count"]]
    times = [row["elapsed_ms"] for row in rows]
    return {
        "recall_at_k": round(sum(row["matched_count"] for row in answerable) / sum(row["expected_count"] for row in answerable), 4),
        "hit_rate_at_k": round(sum(row["matched_count"] > 0 for row in answerable) / len(answerable), 4),
        "all_sources_rate_at_k": round(sum(row["matched_count"] == row["expected_count"] for row in answerable) / len(answerable), 4),
        "mean_ms": round(statistics.mean(times), 2), "p50_ms": round(statistics.median(times), 2),
        "p95_ms": round(percentile(times, .95), 2), "errors": sum(row["status"] != 200 for row in rows),
    }


def render_report(result):
    lines = ["# EvidenceDesk evaluation", "", f"Measured: {result['measured_at']}", "",
             f"Embedding model: `{config.EMBEDDING_MODEL}`. Chat model: `{config.CHAT_MODEL}`. Top k: {result['top_k']}.", "",
             "Synthetic corpus: eight UTF-8 travel documents; 30 questions (24 answerable, six unanswerable).",
             "All results use real PostgreSQL, pgvector, and local Ollama. No provider responses are mocked.", "",
             "## Retrieval", "",
             "Recall counts expected document/page/evidence-span combinations, not merely any hit from the right file.",
             "Unanswerable questions are excluded from recall denominators. Errors count as retrieval misses.", "",
             "| Configuration | Recall@k | Any-source hit@k | All sources@k | Mean ms | p95 ms | Errors |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for name, record in result["retrieval"].items():
        s = record["summary"]
        lines.append(f"| {name} | {s['recall_at_k']:.1%} | {s['hit_rate_at_k']:.1%} | {s['all_sources_rate_at_k']:.1%} | {s['mean_ms']} | {s['p95_ms']} | {s['errors']} |")
    lines += ["", "Hybrid and reranking improvements are not assumed. Compare measured values, including added latency.",
              "The tiny corpus and model/hardware configuration limit generalization.", "", "## Retrieval failures", ""]
    for name, record in result["retrieval"].items():
        misses = [row["id"] for row in record["questions"] if row["matched_count"] < row["expected_count"]]
        lines.append(f"- **{name}:** " + (", ".join(misses) if misses else "no answerable-source misses"))
    if result.get("answers"):
        rows = result["answers"]
        known = [row for row in rows if row["answerable"]]
        unknown = [row for row in rows if not row["answerable"]]
        abstentions = sum(row.get("response", {}).get("abstained") is True for row in unknown)
        errors = sum(row["status"] != 200 for row in rows)
        answer_rate = sum(row.get("response", {}).get("abstained") is False for row in known) / len(known)
        all_citations = sum(row.get("citation_count", 0) for row in rows)
        valid_citations = sum(row.get("valid_citations", 0) for row in rows)
        lines += ["", "## Answers (hybrid, without reranking)", "",
                  f"- Answerable questions receiving an answer: {answer_rate:.1%}.",
                  f"- Correct abstentions on unanswerable questions: {abstentions}/{len(unknown)}.",
                  f"- Request errors: {errors}/{len(rows)}.",
                  f"- Exact source-quotation matches: {valid_citations}/{all_citations} citations.",
                  f"- Mean end-to-end latency: {statistics.mean(row['elapsed_ms'] for row in rows):.0f} ms.", "",
                  "An answered question is not necessarily correct. Exact quotes are not proof of claim support.",
                  "Expected fact-pattern coverage in the JSON is a diagnostic proxy, not a semantic accuracy score.",
                  "See the separate manual evidence review for claim support and completeness.", "", "## Answer failures / omissions", ""]
        for row in rows:
            if row["status"] != 200 or (row["answerable"] and row.get("fact_coverage", 0) < 1) or (not row["answerable"] and not row.get("response", {}).get("abstained", True)):
                lines.append(f"- {row['id']}: status {row['status']}; fact coverage {row.get('fact_coverage')}; abstained {row.get('response', {}).get('abstained')}.")
    return "\n".join(lines) + "\n"


def run(args):
    url = os.environ.get("EVALUATION_DATABASE_URL")
    if not url:
        raise SystemExit("Set EVALUATION_DATABASE_URL to a disposable database ending in _eval")
    with psycopg.connect(url, connect_timeout=3) as connection:
        if not connection.info.dbname.endswith("_eval"):
            raise SystemExit("Refusing to modify a database whose name does not end in _eval")
    os.environ["DATABASE_URL"] = url
    db.initialize()
    if not args.answers_only:
        with db.connect() as connection:
            connection.execute("TRUNCATE documents CASCADE")
    questions = json.loads((ROOT / "questions.json").read_text(encoding="utf-8"))
    result = {"measured_at": datetime.now(timezone.utc).isoformat(), "top_k": args.top_k,
              "embedding_model": config.EMBEDDING_MODEL, "chat_model": config.CHAT_MODEL,
              "python": platform.python_version(), "platform": platform.platform(),
              "cpu_count": os.cpu_count(), "chat_parameters": {"temperature": 0, "seed": 42, "num_ctx": 8192},
              "retrieval": {}, "answers": []}
    args.output.mkdir(parents=True, exist_ok=True)
    output = args.output / "results.json"
    if args.answers_only:
        result = json.loads(output.read_text(encoding="utf-8"))
        if (result["embedding_model"], result["chat_model"], result["top_k"]) != (config.EMBEDDING_MODEL, config.CHAT_MODEL, args.top_k):
            raise SystemExit("Existing retrieval report has different models or top_k")
        if len(result["retrieval"]) != 6:
            raise SystemExit("Complete the six retrieval configurations before evaluating answers only")
        result["answers"] = []
        result["answer_measured_at"] = datetime.now(timezone.utc).isoformat()

    def save():
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
        (args.output / "report.md").write_text(render_report(result), encoding="utf-8")

    with TestClient(app) as client:
        if not args.answers_only:
            for path in sorted((ROOT / "corpus").glob("*.txt")):
                upload = client.post("/api/documents", files={"file": (path.name, path.read_bytes())})
                upload.raise_for_status()
                indexed = client.post(f"/api/documents/{upload.json()['id']}/index")
                indexed.raise_for_status()
            for mode in ("lexical", "vector", "hybrid"):
                for rerank in (False, True):
                    name = mode + ("+rerank" if rerank else "")
                    rows = []
                    for question in questions:
                        start = perf_counter()
                        response = client.post("/api/search", json={"query": question["question"], "mode": mode, "top_k": args.top_k, "rerank": rerank})
                        body = response.json()
                        hits = body.get("results", [])
                        matched = sum(any(source_matches(hit, expected) for hit in hits) for expected in question["expected_sources"])
                        rows.append({"id": question["id"], "status": response.status_code,
                                     "elapsed_ms": round((perf_counter() - start) * 1000, 2),
                                     "expected_count": len(question["expected_sources"]), "matched_count": matched,
                                     "response": body})
                        detail = body.get("detail", {})
                        print(f"{name} {question['id']} status={response.status_code} {detail.get('code', '') if isinstance(detail, dict) else ''}", flush=True)
                    result["retrieval"][name] = {"summary": summarize(rows), "questions": rows}
                    save()
        if args.answers or args.answers_only:
            for question in questions:
                start = perf_counter()
                response = client.post("/api/ask", json={"query": question["question"], "mode": "hybrid", "top_k": args.top_k})
                body = response.json()
                sources = {hit["chunk_id"]: hit for hit in body.get("retrieval", {}).get("results", [])}
                citations = [c for claim in body.get("claims", []) for c in claim["citations"]]
                valid = sum(c["chunk_id"] in sources and c["quote"] in sources[c["chunk_id"]]["text"]
                            and c["document_id"] == sources[c["chunk_id"]]["document_id"]
                            and c["page_number"] == sources[c["chunk_id"]]["page_number"] for c in citations)
                patterns = question["expected_fact_patterns"]
                coverage = sum(bool(re.search(pattern, body.get("answer", ""), re.I)) for pattern in patterns) / len(patterns) if patterns else None
                result["answers"].append({"id": question["id"], "answerable": question["answerable"],
                    "status": response.status_code, "elapsed_ms": round((perf_counter() - start) * 1000, 2),
                    "fact_coverage": coverage, "citation_count": len(citations), "valid_citations": valid, "response": body})
                save()
                print(f"answer {question['id']} status={response.status_code} abstained={body.get('abstained')}", flush=True)
    save()
    print(f"Saved {output}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--answers", action="store_true", help="Also evaluate answers for all 30 questions")
    parser.add_argument("--answers-only", action="store_true", help="Reuse completed retrieval results and corpus; rerun only answer evaluation")
    parser.add_argument("--top-k", type=int, choices=range(1, 9), default=3)
    parser.add_argument("--output", type=Path, default=ROOT / "results")
    run(parser.parse_args())
