"""
Evidence-validator benchmark: latency and correctness per configuration.

Builds real evidence with the local retrieval pipeline, pairs it with
known-correct and known-wrong answers, and sends each case to the
development-only POST /dev/validate endpoint of the running API.

A configuration is only acceptable if it accepts every correct answer and
rejects every wrong one.

Usage (backend running in development mode):
    uv run python scripts/validator_benchmark.py --runs 2 \
        --config baseline:: --config mini-low::low --config nano:gpt-5-nano:
Config format: label:model:reasoning_effort[:structured]
(empty model/effort = project default; structured = "schema")
"""

import argparse
import json
import re
import statistics
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.rag.answer_question import retrieve_evidence  # noqa: E402

API_URL = "http://127.0.0.1:8000"
RESULTS_DIR = Path("data/benchmarks")

# (case name, retrieval question, question shown to validator, answer, expected supported)
CASES = [
    ("salary_lotte_good", "What is Lotte van Dijk's annual gross salary?", None,
     "Lotte van Dijk's annual gross salary is EUR 72,000 [S1][S2].", True),
    ("salary_lotte_wrong_amount", "What is Lotte van Dijk's annual gross salary?", None,
     "Lotte van Dijk's annual gross salary is EUR 82,000 [S1][S2].", False),
    ("salary_thomas_good", "What is Thomas de Boer's monthly gross salary?", None,
     "Thomas de Boer's monthly gross salary is EUR 6,750 [S1][S2].", True),
    ("salary_thomas_swapped_digits", "What is Thomas de Boer's monthly gross salary?", None,
     "Thomas de Boer's monthly gross salary is EUR 6,570 [S1][S2].", False),
    ("tenure_good", "Does Lotte van Dijk's employment agreement confirm that she has worked at her current employer for at least 10 years?", None,
     "No. The documents show her employment started on 3 May 2021 [S1][S2], so they do not "
     "confirm a tenure of at least 10 years.", True),
    ("tenure_overstated", "Does Lotte van Dijk's employment agreement confirm that she has worked at her current employer for at least 10 years?", None,
     "Yes. Lotte van Dijk has worked at Canal Analytics B.V. for more than 10 years [S2].", False),
    ("start_date_wrong", "Does Lotte van Dijk's employment agreement confirm that she has worked at her current employer for at least 10 years?",
     "When did Lotte van Dijk start working at her current employer?",
     "Lotte van Dijk started at Canal Analytics B.V. on 3 May 2020 [S1][S2].", False),
    ("favorite_color_abstain", "What is Lotte van Dijk's favorite color?", None,
     "The available documents do not state Lotte van Dijk's favorite color [S1][S2][S3][S4][S5].", True),
    ("favorite_color_invented", "What is Lotte van Dijk's favorite color?", None,
     "Lotte van Dijk's favorite color is blue [S4].", False),
    ("net_salary_good", "What is Lotte van Dijk's monthly net salary?", None,
     "Lotte van Dijk's monthly net salary is EUR 4,300 [S1][S2].", True),
    ("net_salary_wrong_person", "What is Lotte van Dijk's monthly net salary?",
     "What is Thomas de Boer's monthly net salary?",
     "Thomas de Boer's monthly net salary is EUR 4,300 [S1][S2].", False),
    ("loan_term_good", "What is the loan term for NB-LOAN-2101?", None,
     "The loan term for NB-LOAN-2101 is 48 months [S1][S2].", True),
    ("loan_term_wrong", "What is the loan term for NB-LOAN-2101?", None,
     "The loan term for NB-LOAN-2101 is 60 months [S1][S2].", False),
    ("loan_amount_good", "What is the requested loan amount for NB-LOAN-2101?", None,
     "The requested loan amount for NB-LOAN-2101 is EUR 22,000 [S1][S2].", True),
    ("loan_amount_wrong", "What is the requested loan amount for NB-LOAN-2101?", None,
     "The requested loan amount for NB-LOAN-2101 is EUR 32,000 [S1][S2].", False),
]

# Harder cases. expected=None means the rules leave room for judgement;
# those are compared against the current validator's decision instead.
HARD_CASES = [
    ("two_facts_good", "What is Lotte van Dijk's monthly net salary?",
     "What are Lotte van Dijk's monthly gross and net salary?",
     "Lotte van Dijk's monthly gross salary is EUR 6,000 and her net salary is EUR 4,300 [S1][S2].", True),
    ("two_facts_one_wrong", "What is Lotte van Dijk's monthly net salary?",
     "What are Lotte van Dijk's monthly gross and net salary?",
     "Lotte van Dijk's monthly gross salary is EUR 6,000 and her net salary is EUR 4,700 [S1][S2].", False),
    ("wrong_employer", "What is Lotte van Dijk's annual gross salary?",
     "Who is Lotte van Dijk's employer?",
     "Lotte van Dijk is employed by Delta Infra B.V. as a Data Analyst [S1].", False),
    ("approval_overclaim", "What is the loan term for NB-LOAN-2101?",
     "What is the status of loan NB-LOAN-2101?",
     "Loan NB-LOAN-2101 for EUR 22,000 over 48 months has been approved [S1][S2].", False),
    ("citation_wrong_chunk", "What is Lotte van Dijk's monthly net salary?", None,
     "Lotte van Dijk's monthly net salary is EUR 4,300 [S1].", None),
    ("credit_status_identity", "What is the credit assessment status for Lotte van Dijk?", None,
     "The credit assessment status for Lotte van Dijk (NB-CUST-3001, NB-LOAN-2101) is "
     "DOCUMENT REVIEW PENDING [S2].", None),
]

# Loan-figure attribution. "{doc:<type>}" is replaced with the label of the
# first retrieved source of that document type, so answers cite the right chunk.
# NB-LOAN-9001 is a synthetic fixture: no real document states an instalment.
FIXTURES = {
    "fixture:NB-LOAN-9001": [{
        "source": "tests/fixtures/NB-LOAN-9001/08_loan_offer.pdf",
        "document_type": "loan_offer", "customer_id": "NB-CUST-9001",
        "loan_id": "NB-LOAN-9001", "chunk_index": 0,
        "content": "Loan reference: NB-LOAN-9001 Principal: EUR 20,000 Term: 48 months "
                   "Monthly instalment: EUR 512.40",
    }],
}

ATTRIBUTION_CASES = [
    ("existing_payment_as_requested_instalment", "What is the monthly instalment for loan NB-LOAN-2101?", None,
     "The monthly instalment for NB-LOAN-2101 is EUR 310 [{doc:existing_loan_statement}].", False),
    ("principal_as_instalment", "What is the monthly instalment for loan NB-LOAN-2101?", None,
     "The monthly instalment for NB-LOAN-2101 is EUR 22,000 [{doc:loan_offer}].", False),
    ("instalment_not_stated", "What is the monthly instalment for loan NB-LOAN-2101?", None,
     "The retrieved documents do not state a monthly instalment for NB-LOAN-2101 [{doc:loan_offer}].", True),
    ("existing_payment_correctly_attributed", "What is the monthly payment on Lotte van Dijk's existing loan?", None,
     "Lotte van Dijk's existing loan has a monthly payment of EUR 310 [{doc:existing_loan_statement}].", True),
    ("fixture_instalment_correct", "fixture:NB-LOAN-9001", "What is the monthly instalment for loan NB-LOAN-9001?",
     "The monthly instalment for NB-LOAN-9001 is EUR 512.40 [S1].", True),
    ("fixture_principal_as_instalment", "fixture:NB-LOAN-9001", "What is the monthly instalment for loan NB-LOAN-9001?",
     "The monthly instalment for NB-LOAN-9001 is EUR 20,000 [S1].", False),
]


def resolve_labels(answer: str, sources: list[dict]) -> str:
    def label_for(match):
        for index, source in enumerate(sources, start=1):
            if source.get("document_type") == match.group(1):
                return f"S{index}"
        raise ValueError(f"no retrieved source of type {match.group(1)}")

    return re.sub(r"\{doc:([a-z_]+)\}", label_for, answer)


def build_sources(question: str) -> list[dict]:
    if question in FIXTURES:
        return FIXTURES[question]
    _, _, _, sources = retrieve_evidence(question, top_k=5)
    return [
        {key: source.get(key) for key in
         ("source", "document_type", "customer_id", "loan_id", "chunk_index", "content")}
        for source in sources
    ]


def post(payload: dict) -> tuple[dict, float]:
    request = urllib.request.Request(
        f"{API_URL}/dev/validate",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=300) as response:
        body = json.loads(response.read())
    return body, (time.perf_counter() - started) * 1000


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    rank = (len(ordered) - 1) * pct
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def parse_config(text: str) -> dict:
    parts = (text.split(":") + ["", "", ""])[:4]
    label, model, effort, structured = parts
    return {
        "label": label,
        "model": model or None,
        "reasoning_effort": effort or None,
        "structured_output": True if structured == "schema" else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--config", action="append", required=True)
    parser.add_argument("--output", default="validator_benchmark")
    parser.add_argument("--hard", action="store_true", help="Run the harder cases instead")
    parser.add_argument("--attribution", action="store_true", help="Run the loan-figure attribution cases")
    args = parser.parse_args()

    cases = ATTRIBUTION_CASES if args.attribution else HARD_CASES if args.hard else CASES

    evidence = {question: build_sources(question) for question in {case[1] for case in cases}}
    configs = [parse_config(text) for text in args.config]
    report = {"configs": {}}

    for config in configs:
        rows = []
        for run in range(1, args.runs + 1):
            for name, retrieval_q, shown_q, answer, expected in cases:
                payload = {
                    "question": shown_q or retrieval_q,
                    "answer": resolve_labels(answer, evidence[retrieval_q]),
                    "sources": evidence[retrieval_q],
                    "model": config["model"],
                    "reasoning_effort": config["reasoning_effort"],
                    "structured_output": config["structured_output"],
                }
                body, client_ms = post(payload)
                verdict = body.get("verdict")
                if verdict is None:
                    accepted = None
                else:
                    accepted = bool(
                        verdict["supported"]
                        and verdict["identity_link_proven"]
                        and verdict["status_link_proven"]
                    )
                rows.append({
                    "case": name, "run": run, "expected_supported": expected,
                    "accepted": accepted,
                    "correct": None if expected is None else accepted == expected,
                    "error": body.get("error"), "client_ms": round(client_ms, 1),
                    "timings_ms": body.get("timings_ms") or {},
                    "token_usage": body.get("token_usage") or {},
                    "reason": (verdict or {}).get("reason"),
                })
                print(
                    f"[{config['label']}] run {run} {name:30s} expected={expected!s:5s} "
                    f"accepted={accepted!s:5s} {client_ms:7.0f} ms"
                    + (f"  ERROR {body['error']}" if body.get("error") else "")
                )

        def stage(key):
            values = [r["timings_ms"][key] for r in rows if key in r["timings_ms"]]
            if not values:
                return None
            return {"n": len(values), "median": round(statistics.median(values), 1),
                    "p95": round(percentile(values, 0.95), 1)}

        def tokens(kind):
            values = [r["token_usage"]["evidence_validation"][kind]
                      for r in rows if "evidence_validation" in r["token_usage"]]
            return round(statistics.median(values)) if values else None

        summary = {
            "config": config,
            "cases": len(rows),
            "errors": sum(1 for r in rows if r["error"]),
            "correct": sum(1 for r in rows if r["correct"]),
            "judged": sum(1 for r in rows if r["correct"] is not None),
            "false_accepts": sum(1 for r in rows if r["accepted"] is True and r["expected_supported"] is False),
            "false_rejects": sum(1 for r in rows if r["accepted"] is False and r["expected_supported"] is True),
            "validation_total": stage("evidence_validation"),
            "llm_request": stage("evidence_validation.llm_request"),
            "server_processing": stage("evidence_validation.server_processing"),
            "prompt_prep": stage("evidence_validation.prompt_prep"),
            "parse": stage("evidence_validation.parse"),
            "median_input_tokens": tokens("input_tokens"),
            "median_output_tokens": tokens("output_tokens"),
            "median_reasoning_tokens": tokens("reasoning_tokens"),
        }
        report["configs"][config["label"]] = {"summary": summary, "rows": rows}
        print(json.dumps(summary, indent=1))

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    output = RESULTS_DIR / f"{args.output}.json"
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nReport: {output}")


if __name__ == "__main__":
    main()
