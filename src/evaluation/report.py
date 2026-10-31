"""Baseline comparison and the human-readable Markdown summary."""

import statistics


def compare_to_baseline(current: dict, baseline: dict) -> dict:
    """
    Compare two evaluation reports. Only test IDs present in both are
    compared; added and removed IDs are listed separately.
    """
    now = {r["id"]: r for r in current["results"]}
    before = {r["id"]: r for r in baseline["results"]}
    shared = sorted(now.keys() & before.keys())

    newly_failing = [i for i in shared if before[i]["passed"] and not now[i]["passed"]]
    newly_passing = [i for i in shared if not before[i]["passed"] and now[i]["passed"]]
    behavior_changed = [
        {"id": i, "before": before[i]["actual_behavior"], "now": now[i]["actual_behavior"]}
        for i in shared
        if before[i]["actual_behavior"] != now[i]["actual_behavior"]
    ]

    def median_latency(rows: dict, ids: list[str]) -> float | None:
        values = [rows[i]["latency_ms"] for i in ids if rows[i]["actual_behavior"] != "error"]
        return round(statistics.median(values), 1) if values else None

    before_hash = baseline.get("metadata", {}).get("dataset_sha256")
    now_hash = current.get("metadata", {}).get("dataset_sha256")

    return {
        "baseline_run_id": baseline.get("metadata", {}).get("run_id"),
        # If the dataset changed, a result change may come from the test
        # definition rather than from the agent.
        "dataset_changed": bool(before_hash and now_hash and before_hash != now_hash),
        "compared_ids": len(shared),
        "added_ids": sorted(now.keys() - before.keys()),
        "removed_ids": sorted(before.keys() - now.keys()),
        "pass_count_shared": {
            "baseline": sum(before[i]["passed"] for i in shared),
            "current": sum(now[i]["passed"] for i in shared),
        },
        "newly_failing": newly_failing,
        "newly_passing": newly_passing,
        "behavior_changed": behavior_changed,
        "median_latency_ms_shared": {
            "baseline": median_latency(before, shared),
            "current": median_latency(now, shared),
        },
    }


def _rate(metric: dict) -> str:
    if not metric or metric.get("denominator", 0) == 0:
        return "n/a (0 cases)"
    return f"{metric['rate'] * 100:.1f}% ({metric['numerator']}/{metric['denominator']})"


def _ms(value) -> str:
    return "n/a" if value is None else f"{value:,.0f} ms"


def render_markdown(report: dict) -> str:
    meta = report["metadata"]
    s = report["summary"]
    lat = s["latency"]
    lines = [
        "# NexaBank AI — Evaluation Summary",
        "",
        f"- **Run:** `{meta['run_id']}` ({meta['started_at']})",
        f"- **Agent:** {meta['agent_access']}",
        f"- **Git commit:** `{meta.get('git_commit') or 'unknown'}`"
        + (" (uncommitted changes present)" if meta.get("git_dirty") else ""),
        f"- **Dataset:** `{meta['dataset']}` (sha256 `{meta['dataset_sha256'][:12]}`), "
        f"{s['cases']} cases run" + (f", filters: {meta['filters']}" if meta.get("filters") else ""),
        f"- **Latency measurement:** {meta['latency_note']}",
        "",
        "## Headline metrics",
        "",
        "| Metric | Result |",
        "|---|---|",
        f"| Overall pass (behaviour + citations) | {_rate(s['overall_pass'])} |",
        f"| Behaviour pass | {_rate(s['behavior_pass'])} |",
        f"| Exact-fact accuracy (reference facts in answer cases) | {_rate(s['facts']['exact_fact_accuracy'])} |",
        f"| Correct abstention (abstain cases) | {_rate(s['abstention']['correct_abstention'])} |",
        f"| Abstention precision (abstentions that were warranted) | {_rate(s['abstention']['abstention_precision'])} |",
        f"| Incorrect answers to abstain cases | {_rate(s['abstention']['incorrect_answers_to_abstain_cases'])} |",
        f"| Over-abstention (answer cases not answered) | {_rate(s['abstention']['over_abstention'])} |",
        f"| Conflict rejection | {_rate(s['conflicts']['rejection_rate'])} |",
        f"| Conflicts stopped before generation | {_rate(s['conflicts']['stopped_before_generation'])} |",
        f"| Citation labels map to returned sources | {_rate(s['citations']['label_mapping_valid'])} |",
        f"| Required citation present | {_rate(s['citations']['required_citation_present'])} |",
        f"| Source metadata complete (per source) | {_rate(s['citations']['source_metadata_complete'])} |",
        f"| Expected source type cited | {_rate(s['citations']['expected_source_type'])} |",
        f"| Cited sources match expected customer/loan | {_rate(s['citations']['expected_customer_loan'])} |",
        f"| Expected value found in a cited chunk (heuristic) | {_rate(s['facts']['fact_in_cited_source'])} |",
        f"| Basic validation passed | {_rate(s['validation']['basic_passed'])} |",
        f"| Evidence validation passed | {_rate(s['validation']['evidence_passed'])} |",
        f"| Errors | {s['errors']} |",
        "",
        "Citation mapping only checks that each label points to a returned source. "
        "It does not prove the source supports the claim; the \"found in a cited chunk\" "
        "row is a literal-match heuristic, and only available when chunk text is returned.",
        "",
        "## Validation outcomes",
        "",
        "Identifier conflicts are refused before any validation runs, so they report both "
        "validation flags as false; that is expected, not a validation failure.",
        "",
        "| Outcome | Cases |",
        "|---|---|",
        *[f"| {name} | {count} |" for name, count in s["validation"]["outcomes"].items()],
        "",
        "## Latency",
        "",
    ]

    if lat.get("n"):
        lines += [
            "| Requests | n | Median | Mean | Min | Max | p95 |",
            "|---|---|---|---|---|---|---|",
        ]
        for name, stats in (
            ("All completed", lat),
            ("LLM-backed (conflict refusals excluded)", s.get("latency_llm_requests", {})),
        ):
            if stats.get("n"):
                lines.append(
                    f"| {name} | {stats['n']} | {_ms(stats['median_ms'])} | {_ms(stats['mean_ms'])} | "
                    f"{_ms(stats['min_ms'])} | {_ms(stats['max_ms'])} | {_ms(stats['p95_ms'])}"
                    + ("" if stats["p95_reliable"] else " ⚠️ small sample") + " |"
                )
        lines.append("")
        if not all(
            stats.get("p95_reliable", True)
            for stats in (lat, s.get("latency_llm_requests", {}))
        ):
            lines += [
                "⚠️ p95 from fewer than 20 samples is close to the maximum and should not be "
                "treated as a stable percentile.",
                "",
            ]
    else:
        lines += ["No successful requests to measure.", ""]

    lines += [
        "## By category",
        "",
        "| Category | Passed | Median latency | n | Mean attempts | Max attempts |",
        "|---|---|---|---|---|---|",
    ]
    for category, data in s["by_category"].items():
        lines.append(
            f"| {category} | {_rate(data['passed'])} | {_ms(data['latency'].get('median_ms'))} | "
            f"{data['latency'].get('n', 0)} | {data['attempts_mean'] if data['attempts_mean'] is not None else 'n/a'} | "
            f"{data['attempts_max'] if data['attempts_max'] is not None else 'n/a'} |"
        )

    lines += ["", "## Failed cases", ""]
    if s["failed_cases"]:
        excerpts = {r["id"]: r.get("answer_excerpt") for r in report["results"]}
        for item in s["failed_cases"]:
            lines.append(f"- **`{item['id']}`**: {'; '.join(item['reasons']) or 'see JSON report'}")
            if excerpts.get(item["id"]):
                lines.append(f"  - Answer excerpt: _{excerpts[item['id']]}_")
    else:
        lines.append("None.")

    lines += ["", "## Needs manual review", ""]
    if s["manual_review"]:
        for item in s["manual_review"]:
            lines.append(f"- **`{item['id']}`**: {'; '.join(item['reasons'])}")
    else:
        lines.append("None.")

    comparison = report.get("baseline_comparison")
    if comparison:
        lines += [
            "",
            "## Comparison with baseline",
            "",
            f"Baseline run `{comparison['baseline_run_id']}`; {comparison['compared_ids']} matching test IDs compared.",
            "",
            *(["⚠️ **The dataset changed between the two runs.** Result changes for a test ID may "
               "come from an edited test definition rather than from the agent.", ""]
              if comparison.get("dataset_changed") else []),
            f"- Passed (matching IDs): {comparison['pass_count_shared']['baseline']} → "
            f"{comparison['pass_count_shared']['current']}",
            f"- Newly failing: {comparison['newly_failing'] or 'none'}",
            f"- Newly passing: {comparison['newly_passing'] or 'none'}",
            f"- Behaviour changed: {[c['id'] for c in comparison['behavior_changed']] or 'none'}",
            f"- Median latency (matching IDs): {_ms(comparison['median_latency_ms_shared']['baseline'])} → "
            f"{_ms(comparison['median_latency_ms_shared']['current'])}",
            f"- Added test IDs (not compared): {comparison['added_ids'] or 'none'}",
            f"- Removed test IDs (not compared): {comparison['removed_ids'] or 'none'}",
        ]

    lines += ["", "## Per-case results", "", "| ID | Expected | Actual | Pass | Latency | Attempts |", "|---|---|---|---|---|---|"]
    for r in report["results"]:
        lines.append(
            f"| `{r['id']}` | {r['expected_behavior']} | {r['actual_behavior']} | "
            f"{'✅' if r['passed'] else '❌'} | {_ms(r['latency_ms'])} | {r['validation'].get('attempts', 'n/a')} |"
        )

    return "\n".join(lines) + "\n"
