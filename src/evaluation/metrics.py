"""Aggregate metrics with explicit numerators and denominators."""

import statistics
from collections import defaultdict

from src.evaluation.matching import MATCHED

# Below this many samples a p95 is mostly the maximum; it is still
# reported, but flagged as unreliable.
MIN_SAMPLES_FOR_P95 = 20


def ratio(numerator: int, denominator: int) -> dict:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": round(numerator / denominator, 4) if denominator else None,
    }


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    rank = (len(ordered) - 1) * pct
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def latency_stats(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "median_ms": round(statistics.median(values), 1),
        "mean_ms": round(statistics.fmean(values), 1),
        "min_ms": round(min(values), 1),
        "max_ms": round(max(values), 1),
        "p95_ms": round(percentile(values, 0.95), 1),
        "p95_reliable": len(values) >= MIN_SAMPLES_FOR_P95,
    }


def summarize(results: list[dict]) -> dict:
    """Compute summary metrics from scored case dictionaries."""
    total = len(results)
    errors = [r for r in results if r["actual_behavior"] == "error"]
    completed = [r for r in results if r["actual_behavior"] != "error"]

    answer_cases = [r for r in results if r["expected_behavior"] == "answer"]
    abstain_cases = [r for r in results if r["expected_behavior"] == "abstain"]
    conflict_cases = [r for r in results if r["expected_behavior"] == "reject_conflict"]
    actual_abstentions = [r for r in completed if r["actual_behavior"] == "abstain"]

    # ---- by category ----
    by_category: dict[str, dict] = {}
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        groups[r["category"]].append(r)
    for category, rows in sorted(groups.items()):
        attempts = [
            r["validation"].get("attempts") for r in rows
            if r["validation"].get("attempts") is not None
        ]
        by_category[category] = {
            "passed": ratio(sum(r["passed"] for r in rows), len(rows)),
            "latency": latency_stats([r["latency_ms"] for r in rows if r["actual_behavior"] != "error"]),
            "attempts_mean": round(statistics.fmean(attempts), 2) if attempts else None,
            "attempts_max": max(attempts) if attempts else None,
        }

    # ---- facts ----
    fact_items = [f for r in answer_cases for f in r["facts"]]
    grounding = [
        found
        for r in completed
        if isinstance(r["citations"].get("fact_in_cited_source"), dict)
        for found in r["citations"]["fact_in_cited_source"].values()
    ]

    # ---- citations / metadata ----
    with_labels = [r for r in completed if r["citations"].get("labels")]
    requiring = [
        r for r in completed
        if r["citations"].get("required") and r["actual_behavior"] == "answer"
    ]
    all_sources = [s for r in completed for s in r["sources"]]
    source_type_checked = [r for r in completed if r["citations"].get("source_type_ok") is not None]
    id_checked = [r for r in completed if r["citations"].get("customer_loan_ok") is not None]

    # ---- validation ----
    basic_reported = [r for r in completed if r["validation"].get("basic_validation_passed") is not None]
    evidence_reported = [r for r in completed if r["validation"].get("evidence_validation_passed") is not None]
    outcomes: dict[str, int] = defaultdict(int)
    for r in results:
        outcomes[r["validation"].get("outcome", "unknown")] += 1

    return {
        "cases": total,
        "errors": len(errors),
        "overall_pass": ratio(sum(r["passed"] for r in results), total),
        "behavior_pass": ratio(sum(r["behavior_passed"] for r in results), total),
        "by_category": by_category,
        "facts": {
            "exact_fact_accuracy": ratio(
                sum(f["status"] == MATCHED for f in fact_items), len(fact_items)
            ),
            "answer_cases_all_facts_matched": ratio(
                sum(bool(r["facts"]) and all(f["status"] == MATCHED for f in r["facts"]) for r in answer_cases),
                len(answer_cases),
            ),
            "fact_in_cited_source": ratio(sum(grounding), len(grounding)),
        },
        "abstention": {
            # Of abstain cases, how many were correctly declined?
            "correct_abstention": ratio(sum(r["behavior_passed"] for r in abstain_cases), len(abstain_cases)),
            # Of all abstentions the agent made, how many were on abstain cases?
            "abstention_precision": ratio(
                sum(r["expected_behavior"] == "abstain" for r in actual_abstentions),
                len(actual_abstentions),
            ),
            "incorrect_answers_to_abstain_cases": ratio(
                sum(r["actual_behavior"] == "answer" for r in abstain_cases), len(abstain_cases)
            ),
            "over_abstention": ratio(
                sum(r["actual_behavior"] == "abstain" for r in answer_cases), len(answer_cases)
            ),
        },
        "conflicts": {
            "rejection_rate": ratio(sum(r["behavior_passed"] for r in conflict_cases), len(conflict_cases)),
            "stopped_before_generation": ratio(
                sum(bool(r["validation"].get("stopped_before_generation")) for r in conflict_cases),
                len(conflict_cases),
            ),
        },
        "citations": {
            "label_mapping_valid": ratio(
                sum(bool(r["citations"].get("mapping_valid")) for r in with_labels), len(with_labels)
            ),
            "required_citation_present": ratio(
                sum(bool(r["citations"].get("present")) for r in requiring), len(requiring)
            ),
            "source_metadata_complete": ratio(
                sum(not s["missing_metadata"] for s in all_sources), len(all_sources)
            ),
            "expected_source_type": ratio(
                sum(bool(r["citations"]["source_type_ok"]) for r in source_type_checked),
                len(source_type_checked),
            ),
            "expected_customer_loan": ratio(
                sum(bool(r["citations"]["customer_loan_ok"]) for r in id_checked), len(id_checked)
            ),
        },
        "validation": {
            "basic_passed": ratio(
                sum(bool(r["validation"]["basic_validation_passed"]) for r in basic_reported),
                len(basic_reported),
            ),
            "evidence_passed": ratio(
                sum(bool(r["validation"]["evidence_validation_passed"]) for r in evidence_reported),
                len(evidence_reported),
            ),
            "outcomes": dict(sorted(outcomes.items())),
        },
        "latency": latency_stats([r["latency_ms"] for r in completed]),
        # Conflict refusals skip retrieval and the LLM and take milliseconds,
        # so they are excluded here to show the cost of a real answer.
        "latency_llm_requests": latency_stats([
            r["latency_ms"] for r in completed
            if r["validation"].get("search_mode") != "conflict"
        ]),
        "failed_cases": [
            {"id": r["id"], "reasons": r["failure_reasons"]} for r in results if not r["passed"]
        ],
        "manual_review": [
            {"id": r["id"], "reasons": r["manual_review_reasons"]}
            for r in results if r["manual_review_reasons"]
        ],
    }
