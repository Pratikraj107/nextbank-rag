"""
Run the NexaBank evaluation dataset against the real agent.

By default each question is sent to the real `ask_agent()` in this process
(requires OPENAI_API_KEY). With --api-url the same questions go to an
already-running API instead, which runs the same agent.

Examples:
    uv run python scripts/evaluate_agent.py --limit 3
    uv run python scripts/evaluate_agent.py
    uv run python scripts/evaluate_agent.py --category abstention identifier_conflict
    uv run python scripts/evaluate_agent.py --api-url http://127.0.0.1:8000
    uv run python scripts/evaluate_agent.py --baseline reports/evaluations/<run>.json
"""

import argparse
import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.dataset import DatasetError, load_dataset  # noqa: E402
from src.evaluation.metrics import summarize  # noqa: E402
from src.evaluation.report import compare_to_baseline, render_markdown  # noqa: E402
from src.evaluation.scoring import AgentResponse, CaseOutcome, score_case  # noqa: E402

DEFAULT_DATASET = PROJECT_ROOT / "data/evaluation/nexabank_eval.jsonl"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "reports/evaluations"
DEFAULT_WARMUP_QUESTION = "What is the loan term for NB-LOAN-2101?"


# ------------------------------------------------------------
# Agent access
# ------------------------------------------------------------

class InProcessAgent:
    """Calls the real ask_agent() in this Python process."""

    description = "in-process `ask_agent()` (real agent, real LLM calls)"

    def __init__(self) -> None:
        from src.agents.rag_agent import ask_agent

        self._ask = ask_agent

    def ask(self, question: str) -> AgentResponse:
        # The agent prints progress; keep the evaluation output readable.
        with contextlib.redirect_stdout(io.StringIO()):
            result = self._ask(question)

        return AgentResponse(
            answer=result.get("answer") or "",
            sources=list(result.get("sources") or []),
            search_mode=result.get("search_mode"),
            attempts=result.get("attempts"),
            basic_validation_passed=result.get("is_valid"),
            evidence_validation_passed=result.get("semantic_valid"),
            has_source_content=True,
        )


class ApiAgent:
    """Calls POST /api/chat on a running server (the same real agent)."""

    def __init__(self, base_url: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.description = f"running API at {self.base_url} (real agent over HTTP)"

    def ask(self, question: str) -> AgentResponse:
        request = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=json.dumps({"question": question}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"HTTP {exc.code}") from exc

        return AgentResponse(
            answer=body.get("answer") or "",
            # The API returns source metadata only, positionally S1..Sn.
            sources=list(body.get("sources") or []),
            search_mode=body.get("search_mode"),
            attempts=body.get("attempts"),
            basic_validation_passed=body.get("basic_validation_passed"),
            evidence_validation_passed=body.get("evidence_validation_passed"),
            has_source_content=False,
        )


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

def git_state() -> tuple[str | None, bool]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=PROJECT_ROOT,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        dirty = bool(subprocess.run(
            ["git", "status", "--porcelain"], cwd=PROJECT_ROOT,
            capture_output=True, text=True, check=True,
        ).stdout.strip())
        return commit, dirty
    except (OSError, subprocess.CalledProcessError):
        return None, False


def display_path(path: Path) -> str:
    """Show paths relative to the project when possible."""
    resolved = Path(path).resolve()
    return str(resolved.relative_to(PROJECT_ROOT)) if resolved.is_relative_to(PROJECT_ROOT) else str(resolved)


def latency_note(api_mode: bool, warmup: int) -> str:
    if api_mode:
        note = "warm requests to an already-running API (includes HTTP overhead)"
    else:
        note = "in-process `ask_agent()` calls"
    if warmup:
        note += f"; {warmup} warm-up request(s) excluded from all metrics"
    elif not api_mode:
        note += "; no warm-up, so the first case includes one-time model loading"
    return note + ". Process cold start is not measured."


def run_case(agent, case) -> CaseOutcome:
    started = time.perf_counter()
    try:
        response = agent.ask(case.question)
        return CaseOutcome(case, response, (time.perf_counter() - started) * 1000)
    except Exception as exc:  # recorded per case; the run continues
        return CaseOutcome(
            case, None, (time.perf_counter() - started) * 1000,
            error=f"{type(exc).__name__}: {str(exc)[:200]}",
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--limit", type=int, help="Run only the first N selected cases (smoke test)")
    parser.add_argument("--category", nargs="+", help="Only run these categories")
    parser.add_argument("--warmup", type=int, default=1, help="Warm-up requests excluded from metrics (default 1)")
    parser.add_argument("--warmup-question", default=DEFAULT_WARMUP_QUESTION)
    parser.add_argument("--api-url", help="Evaluate a running API instead of calling ask_agent() in-process")
    parser.add_argument("--timeout", type=float, default=300, help="Per-request timeout in seconds (API mode)")
    parser.add_argument("--baseline", help="Previous evaluation JSON to compare against")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        cases = load_dataset(args.dataset)
    except (DatasetError, OSError) as exc:
        print(exc, file=sys.stderr)
        return 2

    filters = {}
    if args.category:
        known = {case.category for case in cases}
        unknown = set(args.category) - known
        if unknown:
            print(f"Unknown categories {sorted(unknown)}. Known: {sorted(known)}", file=sys.stderr)
            return 2
        cases = [case for case in cases if case.category in args.category]
        filters["category"] = args.category
    if args.limit is not None:
        cases = cases[: args.limit]
        filters["limit"] = args.limit

    if args.api_url:
        agent = ApiAgent(args.api_url, args.timeout)
    else:
        if not os.environ.get("OPENAI_API_KEY"):
            print(
                "OPENAI_API_KEY is not set, so the in-process agent cannot call the LLM.\n"
                "Set it, or evaluate a running server with --api-url http://127.0.0.1:8000",
                file=sys.stderr,
            )
            return 2
        agent = InProcessAgent()

    started_at = datetime.now(timezone.utc)
    run_id = started_at.strftime("%Y%m%dT%H%M%SZ")
    print(f"NexaBank evaluation {run_id}: {len(cases)} case(s) via {agent.description}")

    warmup_ms = []
    for index in range(args.warmup):
        outcome = run_case(agent, SimpleNamespace(question=args.warmup_question))
        warmup_ms.append(round(outcome.latency_ms, 1))
        status = "error: " + outcome.error if outcome.error else "ok"
        print(f"  warm-up {index + 1}/{args.warmup}: {outcome.latency_ms:,.0f} ms ({status}) — excluded")

    results = []
    for number, case in enumerate(cases, start=1):
        result = score_case(run_case(agent, case)).to_dict()
        results.append(result)
        mark = "PASS" if result["passed"] else "FAIL"
        review = "  [review]" if result["manual_review_reasons"] else ""
        print(
            f"  [{number:>2}/{len(cases)}] {mark}  {case.id:45s} "
            f"{result['actual_behavior']:15s} {result['latency_ms']:>8,.0f} ms{review}"
        )

    commit, dirty = git_state()
    dataset_bytes = Path(args.dataset).read_bytes()
    report = {
        "metadata": {
            "run_id": run_id,
            "started_at": started_at.isoformat(timespec="seconds"),
            "agent_access": agent.description,
            "api_url": args.api_url,
            "git_commit": commit,
            "git_dirty": dirty,
            "dataset": display_path(Path(args.dataset)),
            "dataset_sha256": hashlib.sha256(dataset_bytes).hexdigest(),
            "filters": filters,
            "warmup_requests": args.warmup,
            "warmup_latency_ms": warmup_ms,
            "latency_note": latency_note(bool(args.api_url), args.warmup),
        },
        "summary": summarize(results),
        "results": results,
    }

    if args.baseline:
        baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
        report["baseline_comparison"] = compare_to_baseline(report, baseline)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{run_id}.json"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    markdown_path = output_dir / "latest_summary.md"
    markdown_path.write_text(render_markdown(report), encoding="utf-8")

    s = report["summary"]
    lat = s["latency"]

    def show(name, metric):
        if metric["denominator"]:
            print(f"  {name:42s} {metric['numerator']}/{metric['denominator']} ({metric['rate'] * 100:.1f}%)")
        else:
            print(f"  {name:42s} n/a")

    print("\nSummary")
    show("Overall pass", s["overall_pass"])
    show("Behaviour pass", s["behavior_pass"])
    show("Exact-fact accuracy", s["facts"]["exact_fact_accuracy"])
    show("Correct abstention", s["abstention"]["correct_abstention"])
    show("Over-abstention", s["abstention"]["over_abstention"])
    show("Conflict rejection", s["conflicts"]["rejection_rate"])
    show("Citation labels map to sources", s["citations"]["label_mapping_valid"])
    show("Source metadata complete", s["citations"]["source_metadata_complete"])
    show("Evidence validation passed", s["validation"]["evidence_passed"])
    if lat.get("n"):
        print(
            f"  Latency (n={lat['n']}): median {lat['median_ms']:,.0f} ms, p95 {lat['p95_ms']:,.0f} ms"
            + ("" if lat["p95_reliable"] else " (small sample)")
            + f", min {lat['min_ms']:,.0f}, max {lat['max_ms']:,.0f}"
        )
    llm = s["latency_llm_requests"]
    if llm.get("n"):
        print(
            f"  Latency, LLM-backed only (n={llm['n']}): median {llm['median_ms']:,.0f} ms, "
            f"p95 {llm['p95_ms']:,.0f} ms" + ("" if llm["p95_reliable"] else " (small sample)")
        )
    print(f"  Errors: {s['errors']}")
    for item in s["failed_cases"]:
        print(f"  FAILED {item['id']}: {'; '.join(item['reasons'])}")
    for item in s["manual_review"]:
        print(f"  REVIEW {item['id']}: {'; '.join(item['reasons'])}")
    if "baseline_comparison" in report:
        c = report["baseline_comparison"]
        if c["dataset_changed"]:
            print("  WARNING: the dataset changed since the baseline; differences may come from edited tests.")
        print(
            f"  Baseline: {c['compared_ids']} shared IDs; newly failing {c['newly_failing'] or 'none'}; "
            f"newly passing {c['newly_passing'] or 'none'}; added {len(c['added_ids'])}, removed {len(c['removed_ids'])}"
        )
    print(f"\nReport: {display_path(json_path)}\nSummary: {display_path(markdown_path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
