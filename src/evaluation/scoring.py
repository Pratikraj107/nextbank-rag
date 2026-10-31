"""
Score one agent response against one evaluation case.

Everything here is deterministic. Semantic claim-to-evidence support is
NOT judged; the closest automatic signal is `fact_in_cited_source`, which
checks whether each expected value literally appears in a cited chunk.
"""

import re
from dataclasses import dataclass, field

from src.evaluation.dataset import EvalCase
from src.evaluation.matching import (
    AMBIGUOUS,
    CITATION_PATTERN,
    MATCHED,
    fact_label,
    match_fact,
)

# Exact messages the agent returns when it declines to answer.
SYSTEM_ABSTENTION_PREFIXES = (
    "I could not verify the answer sufficiently",
    "I could not find matching documents",
    "The retrieved documents contain no usable text",
)

# Phrases that state the documents lack the requested information.
# "does not confirm" is deliberately absent: it usually answers a yes/no
# question rather than declining it.
ABSTENTION_PATTERNS = [
    r"\b(do|does|did) not (state|mention|contain|include|provide|specify|list|show|record|indicate|say)\b",
    r"\b(no|none of the) (documents?|evidence|information|record|mention)\b[^.]{0,80}\b(about|regarding|on|for|of|mentions?|states?|contains?|includes?)\b",
    r"\bnot (enough|sufficient) (information|evidence)\b",
    r"\binsufficient (information|evidence)\b",
    r"\b(is|are) not (available|stated|mentioned|provided|included|specified)\b",
    r"\bcannot (be determined|determine|answer|find|confirm)\b",
    r"\bcould not (find|verify|determine|confirm)\b",
    r"\bunable to (find|determine|answer|confirm|verify)\b",
    r"\bno (information|data|record|details?) (is|are|was|were )?(available|provided|given|found)\b",
]

# Metadata every returned source should carry.
CORE_SOURCE_FIELDS = ("source", "document_type")


@dataclass
class AgentResponse:
    """The agent's result, normalised across in-process and API calls."""

    answer: str
    sources: list[dict]
    search_mode: str | None
    attempts: int | None
    basic_validation_passed: bool | None
    evidence_validation_passed: bool | None
    # True when sources include chunk text (in-process only).
    has_source_content: bool = False


@dataclass
class CaseOutcome:
    case: EvalCase
    response: AgentResponse | None
    latency_ms: float
    error: str | None = None


@dataclass
class CaseResult:
    id: str
    category: str
    expected_behavior: str
    actual_behavior: str
    behavior_passed: bool
    citation_passed: bool | None
    passed: bool
    latency_ms: float
    error: str | None
    failure_reasons: list[str] = field(default_factory=list)
    manual_review_reasons: list[str] = field(default_factory=list)
    facts: list[dict] = field(default_factory=list)
    forbidden: list[dict] = field(default_factory=list)
    citations: dict = field(default_factory=dict)
    sources: list[dict] = field(default_factory=list)
    validation: dict = field(default_factory=dict)
    answer_excerpt: str | None = None

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def has_abstention_signal(answer: str) -> bool:
    return any(re.search(pattern, answer, re.IGNORECASE) for pattern in ABSTENTION_PATTERNS)


def is_system_abstention(answer: str) -> bool:
    return answer.strip().startswith(SYSTEM_ABSTENTION_PREFIXES)


def cited_labels(answer: str) -> list[str]:
    labels: list[str] = []
    for group in CITATION_PATTERN.findall(answer):
        for label in re.split(r"\s*,\s*", group):
            if label not in labels:
                labels.append(label)
    return labels


def map_citations(labels: list[str], sources: list[dict]) -> tuple[dict[str, dict], list[str]]:
    """
    Map labels to returned sources. Uses each source's `source_id` when the
    agent provides one; otherwise S1 is the first source, S2 the second, ...
    (the order in which the agent assigns labels).
    """
    if any(source.get("source_id") for source in sources):
        by_id = {source.get("source_id"): source for source in sources}
    else:
        by_id = {f"S{index}": source for index, source in enumerate(sources, start=1)}

    mapped = {label: by_id[label] for label in labels if label in by_id}
    unmapped = [label for label in labels if label not in by_id]
    return mapped, unmapped


def source_metadata_issues(source: dict, search_mode: str | None) -> list[str]:
    missing = [name for name in CORE_SOURCE_FIELDS if not source.get(name)]
    # Semantic retrieval works on chunks, so each source should name its chunk.
    if search_mode == "semantic" and source.get("chunk_index") is None:
        missing.append("chunk_index")
    return missing


def _validation_outcome(response: AgentResponse | None, actual_behavior: str) -> str:
    if response is None:
        return "error"
    if response.search_mode == "conflict":
        return "identifier_conflict"
    if response.search_mode == "exact":
        return "exact_search_not_validated"
    if response.evidence_validation_passed is True:
        return "verified_abstention" if actual_behavior == "abstain" else "verified_answer"
    if response.evidence_validation_passed is False:
        return "failed_validation"
    return "validation_not_reported"


def score_case(outcome: CaseOutcome) -> CaseResult:
    case = outcome.case
    response = outcome.response
    failures: list[str] = []
    review: list[str] = []

    if response is None:
        return CaseResult(
            id=case.id, category=case.category, expected_behavior=case.expected_behavior,
            actual_behavior="error", behavior_passed=False, citation_passed=None, passed=False,
            latency_ms=outcome.latency_ms, error=outcome.error,
            failure_reasons=[f"request failed: {outcome.error}"],
            validation={"outcome": "error"},
        )

    answer = response.answer or ""

    # ---- facts -------------------------------------------------------
    facts = [
        {"label": fact_label(fact), "type": fact["type"], "status": match_fact(answer, fact)}
        for fact in case.reference_facts
    ]
    forbidden = [
        {"label": fact_label(fact), "type": fact["type"], "status": match_fact(answer, fact)}
        for fact in case.forbidden_facts
    ]
    all_facts_matched = bool(facts) and all(f["status"] == MATCHED for f in facts)
    forbidden_hits = [f["label"] for f in forbidden if f["status"] == MATCHED]

    for item in facts + forbidden:
        if item["status"] == AMBIGUOUS:
            review.append(f"ambiguous match for '{item['label']}'")

    # ---- behaviour ---------------------------------------------------
    system_abstained = is_system_abstention(answer)
    abstention_signal = has_abstention_signal(answer)

    if response.search_mode == "conflict":
        actual = "reject_conflict"
    elif system_abstained or (abstention_signal and not all_facts_matched):
        actual = "abstain"
    else:
        actual = "answer"

    if case.expected_behavior == "answer":
        behavior_passed = actual == "answer" and all_facts_matched and not forbidden_hits
        if actual == "abstain":
            failures.append("over-abstention: an answerable question was not answered")
        elif actual == "reject_conflict":
            failures.append("treated as an identifier conflict")
        else:
            missing = [f["label"] for f in facts if f["status"] != MATCHED]
            if missing:
                failures.append(f"expected facts not found: {missing}")
        if abstention_signal and all_facts_matched:
            review.append("answer contains both the expected facts and declining language")

    elif case.expected_behavior == "abstain":
        behavior_passed = actual == "abstain" and not forbidden_hits
        if actual != "abstain":
            failures.append("answered a question the documents cannot support")

    else:  # reject_conflict
        behavior_passed = actual in ("reject_conflict", "abstain") and not forbidden_hits
        if actual == "answer":
            failures.append("answered a question with mismatched customer/loan identifiers")

    if forbidden_hits:
        behavior_passed = False
        failures.append(f"forbidden claims present: {forbidden_hits}")

    # ---- citations and sources ---------------------------------------
    labels = cited_labels(answer)
    mapped, unmapped = map_citations(labels, response.sources)
    cited_sources = list(mapped.values())
    checked_sources = cited_sources or response.sources

    metadata = [
        {
            "source": source.get("source"),
            "document_type": source.get("document_type"),
            "customer_id": source.get("customer_id"),
            "loan_id": source.get("loan_id"),
            "chunk_index": source.get("chunk_index"),
            "source_id": source.get("source_id"),
            "missing_metadata": source_metadata_issues(source, response.search_mode),
        }
        for source in response.sources
    ]
    metadata_complete = all(not item["missing_metadata"] for item in metadata)

    citations: dict = {
        "labels": labels,
        "unmapped_labels": unmapped,
        "mapping_valid": (not unmapped) if labels else None,
        "required": case.required_citation,
        "present": bool(labels),
        "metadata_complete": metadata_complete if metadata else None,
        "source_type_ok": None,
        "customer_loan_ok": None,
        "fact_in_cited_source": None,
    }

    if case.required_source_types and actual == "answer":
        citations["source_type_ok"] = any(
            source.get("document_type") in case.required_source_types
            for source in checked_sources
        )

    if (case.expected_customer_id or case.expected_loan_id) and checked_sources and actual == "answer":
        mismatches = [
            source.get("source")
            for source in checked_sources
            if (case.expected_customer_id and source.get("customer_id")
                and source.get("customer_id") != case.expected_customer_id)
            or (case.expected_loan_id and source.get("loan_id")
                and source.get("loan_id") != case.expected_loan_id)
        ]
        citations["customer_loan_ok"] = not mismatches

    # Deterministic grounding heuristic: does each expected value appear
    # in the text of a cited chunk? Only possible when chunk text is returned.
    if response.has_source_content and cited_sources and case.reference_facts:
        grounding = {}
        for fact in case.reference_facts:
            grounding[fact_label(fact)] = any(
                match_fact(source.get("content") or "", fact) == MATCHED
                for source in cited_sources
            )
        citations["fact_in_cited_source"] = grounding
        for label, found in grounding.items():
            if not found and any(f["label"] == label and f["status"] == MATCHED for f in facts):
                review.append(f"'{label}' is in the answer but not found in any cited chunk")

    citation_passed: bool | None = None
    if actual == "answer":
        citation_checks = []
        if case.required_citation:
            citation_checks.append(citations["present"])
            if not citations["present"]:
                failures.append("required citation missing")
        if labels:
            citation_checks.append(citations["mapping_valid"])
            if unmapped:
                failures.append(f"citation labels with no returned source: {unmapped}")
        if citations["metadata_complete"] is False:
            citation_checks.append(False)
            failures.append("returned sources are missing required metadata")
        if citations["source_type_ok"] is False:
            citation_checks.append(False)
            failures.append(f"no cited source of type {case.required_source_types}")
        if citations["customer_loan_ok"] is False:
            citation_checks.append(False)
            failures.append("cited source belongs to a different customer or loan")
        citation_passed = all(citation_checks) if citation_checks else None

    # ---- validation --------------------------------------------------
    validation = {
        "search_mode": response.search_mode,
        "attempts": response.attempts,
        "basic_validation_passed": response.basic_validation_passed,
        "evidence_validation_passed": response.evidence_validation_passed,
        "outcome": _validation_outcome(response, actual),
        # Observable only through the conflict branch: it runs no
        # generation, so it reports search_mode "conflict" and 0 attempts.
        "stopped_before_generation": (
            response.search_mode == "conflict" and response.attempts == 0
        ),
        "system_abstention": system_abstained,
    }

    if case.expected_behavior == "reject_conflict" and actual == "abstain":
        review.append("mismatch was declined, but not by the conflict check")

    passed = behavior_passed and citation_passed is not False

    return CaseResult(
        id=case.id,
        category=case.category,
        expected_behavior=case.expected_behavior,
        actual_behavior=actual,
        behavior_passed=behavior_passed,
        citation_passed=citation_passed,
        passed=passed,
        latency_ms=round(outcome.latency_ms, 1),
        error=None,
        failure_reasons=failures,
        manual_review_reasons=review,
        facts=facts,
        forbidden=forbidden,
        citations=citations,
        sources=metadata,
        validation=validation,
        # Keep answer text only where someone needs to look at it.
        answer_excerpt=answer[:300] if (failures or review) else None,
    )
