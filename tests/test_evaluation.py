"""
Unit tests for the evaluation harness. Agent responses are mocked here;
the evaluation script itself calls the real agent.
"""

import json

import pytest

from src.evaluation.dataset import DatasetError, EvalCase, load_dataset, validate_record
from src.evaluation.matching import (
    AMBIGUOUS,
    MATCHED,
    MISSING,
    extract_amounts,
    match_amount,
    match_date,
    match_fact,
    match_identifier,
    match_quantity,
    match_text,
)
from src.evaluation.metrics import summarize
from src.evaluation.report import compare_to_baseline, render_markdown
from src.evaluation.scoring import AgentResponse, CaseOutcome, cited_labels, map_citations, score_case

# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

def amount(value):
    return {"type": "amount", "value": value, "currency": "EUR"}


def make_case(**overrides) -> EvalCase:
    fields = dict(
        id="case_1", category="supported_fact", question="What is Lotte's salary?",
        expected_behavior="answer", reference_facts=[amount(72000)], required_citation=True,
        notes="", required_source_types=["employment_agreement"],
        expected_customer_id="NB-CUST-3001", expected_loan_id=None, forbidden_facts=[],
    )
    fields.update(overrides)
    return EvalCase(**fields)


def make_source(index=1, **overrides) -> dict:
    source = {
        "source_id": f"S{index}",
        "source": "data/raw/NB-LOAN-2101/docx/09_employment_agreement.docx",
        "document_type": "employment_agreement",
        "customer_id": "NB-CUST-3001",
        "loan_id": "NB-LOAN-2101",
        "chunk_index": index - 1,
        "content": "Annual gross salary: EUR 72,000",
    }
    source.update(overrides)
    return source


def make_response(answer, sources=None, search_mode="semantic", attempts=1,
                  basic=True, evidence=True, content=True) -> AgentResponse:
    return AgentResponse(
        answer=answer,
        sources=[make_source()] if sources is None else sources,
        search_mode=search_mode, attempts=attempts,
        basic_validation_passed=basic, evidence_validation_passed=evidence,
        has_source_content=content,
    )


def score(case, response, latency=1000.0):
    return score_case(CaseOutcome(case, response, latency))


VALID_RECORD = {
    "id": "x", "category": "c", "question": "q?", "expected_behavior": "answer",
    "reference_facts": [amount(1)], "required_citation": True, "notes": "n",
}

# ------------------------------------------------------------
# Dataset schema
# ------------------------------------------------------------

def test_valid_record_has_no_errors():
    assert validate_record(VALID_RECORD, 1) == []


@pytest.mark.parametrize(
    "change, message",
    [
        ({"expected_behavior": "maybe"}, "expected_behavior"),
        ({"reference_facts": []}, "at least one reference fact"),
        ({"reference_facts": [{"type": "amount", "value": "72k"}]}, "amount value"),
        ({"reference_facts": [{"type": "date", "value": "03 May 2021"}]}, "YYYY-MM-DD"),
        ({"reference_facts": [{"type": "pattern", "value": "x"}]}, "unknown fact type"),
        ({"required_citation": "yes"}, "wrong type"),
        ({"surprise": 1}, "unknown fields"),
    ],
)
def test_invalid_records_are_rejected(change, message):
    errors = validate_record({**VALID_RECORD, **change}, 3)
    assert any(message in error for error in errors), errors


def test_missing_field_is_reported():
    record = dict(VALID_RECORD)
    del record["question"]
    assert any("missing required field 'question'" in e for e in validate_record(record, 1))


def test_load_dataset_reports_all_problems(tmp_path):
    path = tmp_path / "eval.jsonl"
    path.write_text(
        json.dumps(VALID_RECORD) + "\n" + "not json\n" + json.dumps(VALID_RECORD) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(DatasetError) as error:
        load_dataset(path)
    assert "invalid JSON" in str(error.value)
    assert "duplicate id 'x'" in str(error.value)


def test_project_dataset_is_valid():
    cases = load_dataset("data/evaluation/nexabank_eval.jsonl")
    assert len(cases) >= 20
    assert {c.expected_behavior for c in cases} == {"answer", "abstain", "reject_conflict"}

# ------------------------------------------------------------
# Fact matching
# ------------------------------------------------------------

@pytest.mark.parametrize(
    "text",
    ["EUR 72,000", "€72,000", "72000 EUR", "EUR 72,000.00", "salary is 72 000 euros", "EUR 72,000."],
)
def test_amount_formatting_variants_match(text):
    assert match_amount(text, 72000) == MATCHED


@pytest.mark.parametrize(
    "text, expected",
    [
        ("EUR 6,570", 6750),        # swapped digits
        ("EUR 16,750", 6750),       # extra digit
        ("EUR 5,083", 5083.33),     # lost precision
        ("EUR 5,083.00", 5083.33),
        ("USD 72,000", 72000),      # wrong currency
        ("NB-LOAN-2101", 2101),     # identifier, not an amount
        ("2021-05-03", 2021),       # date, not an amount
        ("EMP-3001", 3001),
    ],
)
def test_wrong_or_non_amounts_do_not_match(text, expected):
    assert match_amount(text, expected) == MISSING


def test_decimal_amount_matches_exactly():
    assert match_amount("EUR 5,083.33", 5083.33) == MATCHED


def test_dotted_thousands_are_flagged_ambiguous():
    assert match_amount("EUR 72.000", 72000) == AMBIGUOUS


def test_extract_amounts_reads_currency():
    [parsed] = extract_amounts("€ 4,300.00")
    assert parsed.value == 4300 and parsed.currency == "EUR"


@pytest.mark.parametrize(
    "text",
    ["03 May 2021", "3 May 2021", "May 3, 2021", "2021-05-03", "3rd May 2021", "3 mei 2021"],
)
def test_date_formats_match(text):
    assert match_date(text, "2021-05-03") == MATCHED


def test_wrong_date_does_not_match():
    assert match_date("3 May 2020", "2021-05-03") == MISSING


def test_day_month_order_ambiguity_is_flagged():
    # 05/03/2021 is 5 March day-first, 3 May month-first.
    assert match_date("05/03/2021", "2021-05-03") == AMBIGUOUS
    # 30-09-2026 can only be read day-first.
    assert match_date("30-09-2026", "2026-09-30") == MATCHED


def test_quantity_text_and_identifier_matching():
    assert match_quantity("a 48-month term", 48, "month") == MATCHED
    assert match_quantity("148 months", 48, "month") == MISSING
    assert match_text("Works at Canal Analytics B.V. [S1]", "Canal Analytics") == MATCHED
    assert match_text("Works at Canal", "Canal Analytics") == MISSING
    assert match_identifier("IBAN nl00nb00synth3001.", "NL00NB00SYNTH3001") == MATCHED
    assert match_identifier("NB-LOAN-21010", "NB-LOAN-2101") == MISSING


def test_pattern_facts_ignore_citations():
    assert match_fact("Yes [S1].", {"type": "pattern", "value": r"^\W*yes\b"}) == MATCHED
    assert match_fact("No, not yes.", {"type": "pattern", "value": r"^\W*yes\b"}) == MISSING

# ------------------------------------------------------------
# Citations and metadata
# ------------------------------------------------------------

def test_cited_labels_handle_grouped_and_repeated_labels():
    assert cited_labels("A [S1][S2]. B [S2, S3].") == ["S1", "S2", "S3"]


def test_citation_mapping_uses_source_ids_or_position():
    mapped, unmapped = map_citations(["S1", "S3"], [make_source(1), make_source(2)])
    assert list(mapped) == ["S1"] and unmapped == ["S3"]

    positional = [{"source": "a.pdf"}, {"source": "b.pdf"}]
    mapped, unmapped = map_citations(["S2"], positional)
    assert mapped["S2"]["source"] == "b.pdf" and unmapped == []


def test_supported_answer_passes():
    result = score(make_case(), make_response("Her salary is EUR 72,000 [S1]."))

    assert result.passed and result.behavior_passed and result.citation_passed
    assert result.citations["fact_in_cited_source"] == {"amount: 72000": True}
    assert result.answer_excerpt is None


def test_unmapped_citation_fails_citation_check():
    result = score(make_case(), make_response("EUR 72,000 [S4]."))

    assert result.behavior_passed and result.citation_passed is False and not result.passed
    assert result.citations["unmapped_labels"] == ["S4"]


def test_missing_required_citation_fails():
    result = score(make_case(), make_response("EUR 72,000."))

    assert result.citation_passed is False
    assert "required citation missing" in result.failure_reasons


def test_missing_source_metadata_is_reported():
    source = make_source(document_type=None, chunk_index=None)
    result = score(make_case(required_source_types=[]), make_response("EUR 72,000 [S1].", sources=[source]))

    assert result.sources[0]["missing_metadata"] == ["document_type", "chunk_index"]
    assert result.citations["metadata_complete"] is False
    assert not result.passed


def test_source_from_wrong_customer_fails():
    source = make_source(customer_id="NB-CUST-3002")
    result = score(make_case(), make_response("EUR 72,000 [S1].", sources=[source]))

    assert result.citations["customer_loan_ok"] is False and not result.passed


def test_fact_in_answer_but_not_in_cited_chunk_needs_review():
    source = make_source(content="Start date: 03 May 2021")
    result = score(make_case(), make_response("EUR 72,000 [S1].", sources=[source]))

    assert result.passed
    assert any("not found in any cited chunk" in r for r in result.manual_review_reasons)

# ------------------------------------------------------------
# Behaviour classification
# ------------------------------------------------------------

def test_wrong_amount_fails_answer_case():
    result = score(make_case(), make_response("Her salary is EUR 82,000 [S1]."))

    assert not result.behavior_passed and result.actual_behavior == "answer"
    assert result.answer_excerpt


def abstain_case(**overrides):
    return make_case(
        expected_behavior="abstain", reference_facts=[], required_citation=False,
        required_source_types=[],
        forbidden_facts=[{"type": "pattern", "value": r"\b(red|blue|green)\b", "label": "names a colour"}],
        **overrides,
    )


def test_correct_abstention():
    result = score(abstain_case(), make_response("The documents do not state her favorite color [S1]."))

    assert result.actual_behavior == "abstain" and result.passed
    assert result.validation["outcome"] == "verified_abstention"


def test_system_abstention_counts_as_abstention():
    message = ("I could not verify the answer sufficiently against the retrieved evidence. "
               "Please review the source documents or refine the question.")
    result = score(abstain_case(), make_response(message, sources=[], basic=False, evidence=False))

    assert result.actual_behavior == "abstain" and result.passed
    assert result.validation["outcome"] == "failed_validation"


def test_invented_answer_to_abstention_case_fails():
    result = score(abstain_case(), make_response("Her favorite color is blue [S1]."))

    assert result.actual_behavior == "answer" and not result.passed
    assert any("forbidden claims" in r for r in result.failure_reasons)


def test_declining_while_inventing_still_fails():
    answer = "The documents do not state it, but it is probably blue."
    result = score(abstain_case(), make_response(answer))

    assert result.actual_behavior == "abstain" and not result.passed


def test_over_abstention_is_detected():
    result = score(make_case(), make_response("The documents do not mention her salary [S1]."))

    assert result.actual_behavior == "abstain" and not result.passed
    assert any("over-abstention" in r for r in result.failure_reasons)


def conflict_case():
    return make_case(
        expected_behavior="reject_conflict", reference_facts=[], required_citation=False,
        required_source_types=[], forbidden_facts=[{"type": "pattern", "value": r"^\W*yes\b"}],
    )


def test_conflict_rejection_via_conflict_route():
    response = make_response("I cannot answer this question because the customer and loan identifiers conflict.",
                             sources=[], search_mode="conflict", attempts=0, basic=False, evidence=False)
    result = score(conflict_case(), response)

    assert result.passed and result.actual_behavior == "reject_conflict"
    assert result.validation["stopped_before_generation"] is True
    assert result.validation["outcome"] == "identifier_conflict"


def test_conflict_case_answered_fails():
    result = score(conflict_case(), make_response("Yes, the review is pending [S1]."))

    assert not result.passed and result.actual_behavior == "answer"
    assert result.validation["stopped_before_generation"] is False


def test_conflict_declined_without_conflict_route_passes_with_review():
    result = score(conflict_case(), make_response("I cannot confirm that from these documents."))

    assert result.passed and result.actual_behavior == "abstain"
    assert result.manual_review_reasons


def test_failed_request_is_recorded_as_error():
    result = score_case(CaseOutcome(make_case(), None, 120.0, error="TimeoutError: timed out"))

    assert result.actual_behavior == "error" and not result.passed
    assert result.validation["outcome"] == "error"

# ------------------------------------------------------------
# Summary metrics and reporting
# ------------------------------------------------------------

def test_summary_of_empty_run_has_no_rates():
    summary = summarize([])

    assert summary["cases"] == 0
    assert summary["overall_pass"] == {"numerator": 0, "denominator": 0, "rate": None}
    assert summary["latency"] == {"n": 0}


def test_summary_counts_and_denominators():
    results = [
        score(make_case(id="a"), make_response("EUR 72,000 [S1]."), 1000).to_dict(),
        score(make_case(id="b"), make_response("The documents do not mention it."), 2000).to_dict(),
        score(abstain_case(id="c", category="abstention"), make_response("Not stated; the documents do not state it."), 3000).to_dict(),
        score_case(CaseOutcome(make_case(id="d"), None, 50, error="RuntimeError: x")).to_dict(),
    ]

    summary = summarize(results)

    assert summary["overall_pass"] == {"numerator": 2, "denominator": 4, "rate": 0.5}
    assert summary["errors"] == 1
    assert summary["abstention"]["over_abstention"]["numerator"] == 1
    assert summary["abstention"]["over_abstention"]["denominator"] == 3
    assert summary["abstention"]["abstention_precision"] == {"numerator": 1, "denominator": 2, "rate": 0.5}
    assert summary["latency"]["n"] == 3  # the error is excluded
    assert summary["latency"]["p95_reliable"] is False
    assert {item["id"] for item in summary["failed_cases"]} == {"b", "d"}


def test_baseline_comparison_handles_added_and_removed_ids():
    def report(rows):
        return {"metadata": {"run_id": "r"}, "results": rows}

    def row(case_id, passed, behavior="answer", latency=1000):
        return {"id": case_id, "passed": passed, "actual_behavior": behavior, "latency_ms": latency}

    baseline = report([row("kept_pass", True), row("kept_fail", False), row("removed", True)])
    current = report([row("kept_pass", False, "abstain"), row("kept_fail", True), row("added", True)])

    comparison = compare_to_baseline(current, baseline)

    assert comparison["compared_ids"] == 2
    assert comparison["added_ids"] == ["added"]
    assert comparison["removed_ids"] == ["removed"]
    assert comparison["newly_failing"] == ["kept_pass"]
    assert comparison["newly_passing"] == ["kept_fail"]
    assert comparison["behavior_changed"] == [{"id": "kept_pass", "before": "answer", "now": "abstain"}]
    assert comparison["dataset_changed"] is False


def test_baseline_comparison_flags_dataset_change():
    def report(digest):
        return {"metadata": {"run_id": "r", "dataset_sha256": digest}, "results": []}

    assert compare_to_baseline(report("a"), report("b"))["dataset_changed"] is True
    assert compare_to_baseline(report("a"), report("a"))["dataset_changed"] is False


def test_markdown_renders_for_small_run():
    results = [score(make_case(), make_response("EUR 72,000 [S1]."), 1000).to_dict()]
    markdown = render_markdown({
        "metadata": {
            "run_id": "r1", "started_at": "now", "agent_access": "mock", "git_commit": "abc",
            "dataset": "d.jsonl", "dataset_sha256": "0" * 64, "latency_note": "test",
        },
        "summary": summarize(results),
        "results": results,
    })

    assert "Overall pass" in markdown and "small sample" in markdown


# ------------------------------------------------------------
# Forbidden-claim patterns in the project dataset must respect negation.
# These sentences are real agent answers that were wrongly flagged before.
# ------------------------------------------------------------

def dataset_pattern(label: str) -> dict:
    for case in load_dataset("data/evaluation/nexabank_eval.jsonl"):
        for fact in case.forbidden_facts:
            if fact.get("label") == label:
                return fact
    raise AssertionError(f"pattern {label!r} not in dataset")


@pytest.mark.parametrize(
    "text, forbidden",
    [
        ("No. The employment agreement lists a start date of 03 May 2021, which does not "
         "indicate she has worked for the employer for at least 10 years [S2].", False),
        ("Yes. She has worked there for 10 years.", True),
        ("She has worked at Canal Analytics for ten years [S1].", True),
    ],
)
def test_tenure_pattern_respects_negation(text, forbidden):
    fact = dataset_pattern("claims 10 years of employment")
    assert (match_fact(text, fact) == MATCHED) is forbidden


@pytest.mark.parametrize(
    "text, forbidden",
    [
        ('The status is "DOCUMENT REVIEW PENDING" [S2]. The available documents do not show '
         "that the loan has been approved.", False),
        ("The loan has been approved [S1].", True),
        ("Status is pending. It was approved yesterday.", True),
    ],
)
def test_approval_pattern_respects_negation(text, forbidden):
    fact = dataset_pattern("states the loan is approved")
    assert (match_fact(text, fact) == MATCHED) is forbidden
