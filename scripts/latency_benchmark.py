"""
Latency and regression benchmark for the running NexaBank API.

Sends each benchmark question to POST /api/chat several times, checks the
answer against the expected behaviour, and reports median / p95 latency per
stage using the development-only `timings_ms` field.

Usage (backend must be running):
    uv run python scripts/latency_benchmark.py --runs 3 --label after
    uv run python scripts/latency_benchmark.py --cold --label after-cold

Uses only the standard library so it does not affect the backend.
"""

import argparse
import json
import re
import statistics
import time
import urllib.error
import urllib.request
from pathlib import Path

API_URL = "http://127.0.0.1:8000"
RESULTS_DIR = Path("data/benchmarks")

NEGATION = re.compile(
    r"\b(no|not|cannot|can't|does not|doesn't|do not|don't|unable|insufficient|"
    r"only|since|started|start date)\b",
    re.IGNORECASE,
)
COLORS = re.compile(
    r"\b(red|blue|green|yellow|orange|purple|pink|black|white|grey|gray|brown)\b",
    re.IGNORECASE,
)


def has_valid_citations(body: dict) -> bool:
    labels = {int(n) for n in re.findall(r"S(\d+)", " ".join(re.findall(r"\[[^\]]*\]", body["answer"])))}
    return bool(labels) and all(1 <= n <= len(body["sources"]) for n in labels)


def check_salary_lotte(body: dict) -> tuple[bool, str]:
    ok = bool(re.search(r"72[,.]?000", body["answer"])) and has_valid_citations(body)
    return ok, "mentions EUR 72,000 with valid citations"


def check_salary_thomas(body: dict) -> tuple[bool, str]:
    ok = bool(re.search(r"6[,.]?750", body["answer"])) and has_valid_citations(body)
    return ok, "mentions EUR 6,750 with valid citations"


def check_tenure(body: dict) -> tuple[bool, str]:
    answer = body["answer"]
    affirms = re.match(r"\s*yes\b", answer, re.IGNORECASE) is not None
    ok = not affirms and bool(NEGATION.search(answer))
    return ok, "does not affirm a 10-year tenure"


def check_favorite_color(body: dict) -> tuple[bool, str]:
    answer = body["answer"]
    ok = bool(NEGATION.search(answer)) and not COLORS.search(answer)
    return ok, "says the documents do not state it, names no colour"


def check_conflict(body: dict) -> tuple[bool, str]:
    ok = body["search_mode"] == "conflict" and not body["sources"]
    return ok, "routed to conflict, no sources, no answer generated"


def check_net_salary_citations(body: dict) -> tuple[bool, str]:
    sources_ok = body["sources"] and all(
        s.get("loan_id") == "NB-LOAN-2101" for s in body["sources"]
    )
    ok = (
        bool(re.search(r"4[,.]?300", body["answer"]))
        and has_valid_citations(body)
        and bool(sources_ok)
    )
    return ok, "mentions EUR 4,300, citations map to NB-LOAN-2101 sources"


CASES = [
    ("salary_lotte", "What is Lotte van Dijk's annual gross salary?", check_salary_lotte),
    ("salary_thomas", "What is Thomas de Boer's monthly gross salary?", check_salary_thomas),
    (
        "tenure_claim",
        "Does Lotte van Dijk's employment agreement confirm that she has worked at her "
        "current employer for at least 10 years?",
        check_tenure,
    ),
    ("favorite_color", "What is Lotte van Dijk's favorite color?", check_favorite_color),
    (
        "conflict",
        "Does the credit analyst note for loan NB-LOAN-2101 confirm that Thomas de Boer's "
        "document review is pending?",
        check_conflict,
    ),
    ("net_salary_citations", "What is Lotte van Dijk's monthly net salary?", check_net_salary_citations),
]


def ask(question: str, timeout: float = 300) -> tuple[dict, float]:
    request = urllib.request.Request(
        f"{API_URL}/api/chat",
        data=json.dumps({"question": question}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = json.loads(response.read())
    return body, (time.perf_counter() - started) * 1000


def wait_for_health(timeout: float = 180) -> float:
    started = time.perf_counter()
    while time.perf_counter() - started < timeout:
        try:
            with urllib.request.urlopen(f"{API_URL}/health", timeout=2) as response:
                if json.loads(response.read()).get("status") == "ok":
                    return (time.perf_counter() - started) * 1000
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            pass
        time.sleep(0.25)
    raise TimeoutError("Backend did not become healthy.")


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * pct
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def summarize_tokens(runs: list[dict]) -> dict:
    tokens: dict[str, list[int]] = {}
    for run in runs:
        for stage, usage in (run.get("token_usage") or {}).items():
            for kind, value in usage.items():
                tokens.setdefault(f"{stage}.{kind}", []).append(value)

    return {
        key: {"n": len(values), "median": statistics.median(values), "max": max(values)}
        for key, values in sorted(tokens.items())
    }


def summarize(runs: list[dict]) -> dict:
    stages: dict[str, list[float]] = {}
    for run in runs:
        for stage, value in run["timings_ms"].items():
            stages.setdefault(stage, []).append(value)
        stages.setdefault("client_round_trip", []).append(run["client_ms"])

    return {
        stage: {
            "n": len(values),
            "median": round(statistics.median(values), 1),
            "p95": round(percentile(values, 0.95), 1),
        }
        for stage, values in sorted(stages.items())
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--label", default="run")
    parser.add_argument("--only", nargs="*", help="Case names to run")
    parser.add_argument(
        "--cold",
        action="store_true",
        help="Touch src/api/main.py to make uvicorn --reload restart, then time the first request.",
    )
    args = parser.parse_args()

    cases = [case for case in CASES if not args.only or case[0] in args.only]
    results = []

    if args.cold:
        Path("src/api/main.py").touch()
        time.sleep(1.5)
        health_ms = wait_for_health()
        name, question, check = cases[0]
        body, client_ms = ask(question)
        passed, rule = check(body)
        results.append(
            {"case": name, "run": 0, "cold": True, "startup_to_health_ms": round(health_ms, 1),
             "client_ms": round(client_ms, 1), "timings_ms": body.get("timings_ms") or {},
             "attempts": body["attempts"], "search_mode": body["search_mode"],
             "evidence_validation_passed": body["evidence_validation_passed"],
             "passed": passed, "rule": rule, "answer": body["answer"]}
        )
        print(f"[cold] startup→health {health_ms:.0f} ms, first request {client_ms:.0f} ms, passed={passed}")
    else:
        for run in range(1, args.runs + 1):
            for name, question, check in cases:
                body, client_ms = ask(question)
                passed, rule = check(body)
                results.append(
                    {"case": name, "run": run, "cold": False, "client_ms": round(client_ms, 1),
                     "timings_ms": body.get("timings_ms") or {}, "attempts": body["attempts"],
                     "token_usage": body.get("token_usage") or {},
                     "search_mode": body["search_mode"],
                     "basic_validation_passed": body["basic_validation_passed"],
                     "evidence_validation_passed": body["evidence_validation_passed"],
                     "passed": passed, "rule": rule, "answer": body["answer"]}
                )
                print(
                    f"[{run}] {name:22s} {client_ms:8.0f} ms  attempts={body['attempts']} "
                    f"evidence={body['evidence_validation_passed']} passed={passed}"
                )

    report = {
        "label": args.label,
        "by_case": {
            name: summarize([r for r in results if r["case"] == name])
            for name in dict.fromkeys(r["case"] for r in results)
        },
        "llm_cases_overall": summarize([r for r in results if r["search_mode"] != "conflict"]),
        "token_usage": summarize_tokens(results),
        "results": results,
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    output = RESULTS_DIR / f"latency_{args.label}.json"
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    failed = [r for r in results if not r["passed"]]
    print(f"\nPassed {len(results) - len(failed)}/{len(results)} checks. Report: {output}")
    for r in failed:
        print(f"  FAILED {r['case']} (run {r['run']}): {r['rule']}\n    {r['answer'][:300]}")


if __name__ == "__main__":
    main()
