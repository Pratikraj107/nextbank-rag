
import json
import os
import re
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from src.llm.client import create_response, get_openai_client
from src.observability.timing import agent_attempt, timed_stage
from src.rag.answer_question import answer_question, llm_options, retrieve_evidence
from src.rag.document_subjects import SEPARATE_CREDIT_TYPES, describe_document
from src.retrieval.exact_search import exact_search
from src.retrieval.query_analyzer import QueryAnalysis, QueryAnalyzer


# ============================================================
# CONFIGURATION
# ============================================================

VALIDATION_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")
# Measured validations used at most ~1,400 output tokens (reasoning
# included); the cap only stops runaway responses.
VALIDATION_MAX_OUTPUT_TOKENS = os.getenv("VALIDATION_MAX_OUTPUT_TOKENS", "4000")
# "low" matched the default effort's decision on every case of the
# validator benchmark (48/48) at about half the latency. "minimal" was
# faster but accepted an identity link the default rejects, and
# gpt-5-nano accepted a wrong salary, so neither is used.
# See docs/latency-optimization.md, section 12.
VALIDATION_REASONING_EFFORT = os.getenv("VALIDATION_REASONING_EFFORT", "low")
VALIDATION_STRUCTURED_OUTPUT = os.getenv("VALIDATION_STRUCTURED_OUTPUT", "false").lower() == "true"

MAX_ATTEMPTS = 2
# Attempt 1 retrieves FIRST_TOP_K chunks; a retry widens to RETRY_TOP_K.
FIRST_TOP_K = 5
RETRY_TOP_K = 8

# Why the latest attempt failed. Only some failures are worth retrying:
#   citation       - the answer's citation labels were missing or invalid;
#                    a new generation can fix this.
#   unsupported    - the evidence validator rejected the answer; retry
#                    only if a wider search would add new evidence.
#   no_evidence    - retrieval found nothing; the same filters would
#                    find nothing again, so do not retry.
#   validator_error- the validator call failed; regenerating the answer
#                    cannot fix that, so abstain.
FAILURE_CITATION = "citation"
FAILURE_UNSUPPORTED = "unsupported"
FAILURE_NO_EVIDENCE = "no_evidence"
FAILURE_VALIDATOR_ERROR = "validator_error"


# ============================================================
# AGENT STATE
# ============================================================

class AgentState(TypedDict):
    question: str
    answer: str
    sources: list[dict[str, Any]]
    attempts: int
    is_valid: bool
    semantic_valid: bool
    validation_feedback: str
    search_mode: str
    exact_term: str
    entity_conflict: str
    query_analysis: dict[str, Any]
    failure_reason: str
    retry_can_add_evidence: bool


# ============================================================
# NODE 1: ROUTE THE QUESTION
# ============================================================

def route_query(state: AgentState) -> dict:
    """
    Route exact searches directly to literal search.

    For all other questions, analyze customer and loan IDs
    before allowing semantic retrieval.
    """

    question = state["question"].strip()

    exact_patterns = [
        r"^search exact text:\s*(.+)$",
        r"""(?:does|do)\s+["'](.+?)["']\s+
            (?:appear|occur|exist)\s+
            (?:anywhere|in the documents)""",
        r"""find all documents containing\s+["'](.+?)["']""",
    ]

    for pattern in exact_patterns:
        match = re.search(
            pattern,
            question,
            flags=re.IGNORECASE | re.VERBOSE,
        )

        if match:
            term = match.group(1).strip()

            if term:
                print("[Router] Search mode: exact")
                print(f"[Router] Exact term: {term}")

                return {
                    "search_mode": "exact",
                    "exact_term": term,
                    "entity_conflict": "",
                    "query_analysis": {},
                }

    # Analyze entity relationships before semantic retrieval.
    with timed_stage("query_analysis"):
        analysis = QueryAnalyzer().analyze(question)
    analysis_data = analysis.to_dict()

    if analysis.entity_conflict:
        print("[Router] Entity conflict detected.")
        print(f"[Router] {analysis.entity_conflict}")

        return {
            "search_mode": "conflict",
            "exact_term": "",
            "entity_conflict": analysis.entity_conflict,
            "query_analysis": analysis_data,
        }

    print("[Router] Search mode: semantic RAG")

    return {
        "search_mode": "semantic",
        "exact_term": "",
        "entity_conflict": "",
        "query_analysis": analysis_data,
    }


def route_search_mode(state: AgentState) -> str:
    """Choose the conflict, exact-search, or RAG branch."""

    if state.get("entity_conflict"):
        return "entity_conflict"

    if state.get("search_mode") == "exact":
        return "exact_search"

    return "answer"


# ============================================================
# NODE 2: ENTITY CONFLICT
# ============================================================

def entity_conflict_node(state: AgentState) -> dict:
    """
    Reject known customer/loan mismatches without retrieval
    or answer generation.
    """

    conflict = state.get(
        "entity_conflict",
        "The customer and loan identifiers conflict.",
    )

    return {
        "answer": (
            "I cannot answer this question because the customer "
            "and loan identifiers conflict.\n\n"
            f"{conflict}\n\n"
            "Please verify the customer and loan IDs and try again."
        ),
        "sources": [],
        "is_valid": False,
        "semantic_valid": False,
        "validation_feedback": (
            "Retrieval skipped because a known entity conflict "
            "was detected before answering."
        ),
    }


# ============================================================
# NODE 3: EXACT SEARCH
# ============================================================

def exact_search_node(state: AgentState) -> dict:
    """
    Search normalized documents for literal text.
    This branch does not require LLM answer generation.
    """

    term = state.get("exact_term", "").strip()

    if not term:
        return {
            "answer": "No exact search term was provided.",
            "sources": [],
        }

    with timed_stage("exact_search"):
        result = exact_search(
            term,
            case_sensitive=False,
            max_results=20,
        )

    documents_scanned = result.get("documents_scanned", 0)
    documents_matched = result.get("documents_matched", 0)
    total_occurrences = result.get("total_occurrences", 0)
    results = result.get("results", [])

    lines = [
        f"Exact search term: {term}",
        f"Documents scanned: {documents_scanned}",
        f"Matching documents: {documents_matched}",
        f"Total occurrences: {total_occurrences}",
        "",
    ]

    if not results:
        lines.append(
            "No literal matches were found in the normalized "
            "document content that was scanned."
        )
    else:
        lines.append("MATCHING DOCUMENTS")

        for index, item in enumerate(results, start=1):
            lines.extend(
                [
                    "",
                    f"{index}. Source: {item.get('source', 'Unknown')}",
                    f"   Document ID: {item.get('document_id', 'Unknown')}",
                    f"   Customer ID: {item.get('customer_id', 'Unknown')}",
                    f"   Loan ID: {item.get('loan_id', 'Unknown')}",
                    f"   Document type: {item.get('document_type', 'Unknown')}",
                    f"   Match count: {item.get('match_count', 0)}",
                    f"   Excerpt: {item.get('excerpt', '')}",
                ]
            )

        if result.get("results_truncated"):
            lines.append(
                "\nAdditional matching results were omitted."
            )

    return {
        "answer": "\n".join(lines),
        "sources": results,
    }


# ============================================================
# NODE 4: GENERATE AN ANSWER
# ============================================================

def answer_node(state: AgentState) -> dict:
    """
    Retrieve evidence and generate an answer.

    Attempt 1 retrieves up to 5 chunks.
    Attempt 2 retrieves up to 8 chunks.
    """

    attempt = state.get("attempts", 0) + 1
    top_k = FIRST_TOP_K if attempt == 1 else RETRY_TOP_K

    print(
        f"\n[Agent] Attempt {attempt}: "
        f"retrieving evidence (top_k={top_k})"
    )

    with agent_attempt(attempt), timed_stage("attempt_answer_total"):
        result = answer_question(
            question=state["question"],
            top_k=top_k,
            # Reuse the analysis from route_query instead of repeating it.
            analysis=_analysis_from_state(state),
        )

    answer = result.get("answer", "")
    sources = result.get("sources", [])

    return {
        "answer": answer,
        "sources": sources,
        "attempts": attempt,
        "is_valid": False,
        "semantic_valid": False,
        "validation_feedback": "",
        "failure_reason": "",
        "retry_can_add_evidence": False,
    }


def _analysis_from_state(state: AgentState) -> QueryAnalysis | None:
    data = state.get("query_analysis") or {}

    if not data:
        return None

    return QueryAnalysis(**data)


# ============================================================
# NODE 5: BASIC VALIDATION
# ============================================================

def validate_basic_node(state: AgentState) -> dict:
    with agent_attempt(state.get("attempts", 0)), timed_stage("basic_validation"):
        return _validate_basic(state)


def _validate_basic(state: AgentState) -> dict:
    """
    Perform preliminary checks on retrieved evidence and
    citation labels before invoking the LLM evidence validator.
    """

    answer = state.get("answer", "")
    sources = state.get("sources", [])

    if not sources:
        feedback = "No evidence retrieved."

        print(f"[Basic Validator] {feedback}")

        return {
            "is_valid": False,
            "validation_feedback": feedback,
            "failure_reason": FAILURE_NO_EVIDENCE,
        }

    cited_labels = re.findall(
        r"\[(S\d+)\]",
        answer,
    )

    unique_labels = sorted(
        set(cited_labels),
        key=lambda label: int(label[1:]),
    )

    valid_labels = {
        f"S{index}"
        for index in range(1, len(sources) + 1)
    }

    invalid_labels = [
        label
        for label in unique_labels
        if label not in valid_labels
    ]

    print(f"[Basic Validator] Citations: {unique_labels}")

    distinct_files = {
        source.get("source")
        for source in sources
        if source.get("source")
    }

    print(f"[Basic Validator] Distinct files: {len(distinct_files)}")

    if len(distinct_files) <= 1:
        print(
            "[Basic Validator] Multiple cited chunks may come "
            "from the same source file."
        )

    if invalid_labels:
        feedback = (
            f"Invalid citation labels: {invalid_labels}. "
            f"Available labels: {sorted(valid_labels)}"
        )

        print(f"[Basic Validator] {feedback}")

        return {
            "is_valid": False,
            "validation_feedback": feedback,
            "failure_reason": FAILURE_CITATION,
        }

    if not unique_labels:
        feedback = "The answer contains no source citations."

        print(f"[Basic Validator] {feedback}")

        return {
            "is_valid": False,
            "validation_feedback": feedback,
            "failure_reason": FAILURE_CITATION,
        }

    cited_sources = [
        sources[int(label[1:]) - 1]
        for label in unique_labels
    ]

    metadata_issue = (
        _cited_metadata_issue(state, cited_sources)
        or _loan_attribution_issue(state, cited_sources)
    )

    if metadata_issue:
        print(f"[Basic Validator] {metadata_issue}")

        return {
            "is_valid": False,
            "validation_feedback": metadata_issue,
            "failure_reason": FAILURE_CITATION,
        }

    print("[Basic Validator] Checks passed.")

    return {
        "is_valid": True,
        "validation_feedback": "Basic citation checks passed.",
    }


# Questions about the terms of a specific requested loan.
LOAN_TERM_QUESTION = re.compile(
    r"\b(instal+ments?|installments?|monthly (re)?payments?|repayments?|"
    r"principal|interest rate|loan term|term of the loan|duration)\b",
    re.IGNORECASE,
)
# Questions explicitly about another credit agreement are exempt.
OTHER_CREDIT_QUESTION = re.compile(
    r"\b(existing|current|other|previous|outstanding) (loans?|credit|debts?)\b",
    re.IGNORECASE,
)


def _loan_attribution_issue(state: AgentState, cited_sources: list[dict]) -> str | None:
    """
    Deterministic guard: a question about the terms of a named loan must
    not be answered solely from documents that describe a separate,
    existing credit agreement (e.g. an existing-loan statement filed with
    that application). Mixed or ambiguous cases are left to the evidence
    validator, which reads the content.
    """
    loan_id = (state.get("query_analysis") or {}).get("loan_id")
    question = state.get("question", "")

    if (
        not loan_id
        or not cited_sources
        or not LOAN_TERM_QUESTION.search(question)
        or OTHER_CREDIT_QUESTION.search(question)
    ):
        return None

    if all(source.get("document_type") in SEPARATE_CREDIT_TYPES for source in cited_sources):
        return (
            f"The answer to a question about {loan_id}'s terms cites only documents "
            "describing a separate existing credit agreement."
        )

    return None


def _cited_metadata_issue(state: AgentState, cited_sources: list[dict]) -> str | None:
    """
    Deterministic checks on the sources an answer cites:
    - each has the metadata needed to attribute it (file, document type);
    - none belongs to a different customer or loan than the question names.

    Sources without a customer or loan ID (e.g. some CSV records) are not
    treated as mismatches; the evidence validator still judges them.
    """
    analysis = state.get("query_analysis") or {}
    expected_customer = analysis.get("customer_id")
    expected_loan = analysis.get("loan_id")

    for source in cited_sources:
        label = source.get("source_id", "?")

        if not source.get("source") or not source.get("document_type"):
            return f"Cited source {label} is missing file or document-type metadata."

        customer = source.get("customer_id")
        loan = source.get("loan_id")

        if expected_customer and customer and customer != expected_customer:
            return (
                f"Cited source {label} belongs to {customer}, "
                f"but the question is about {expected_customer}."
            )

        if expected_loan and loan and loan != expected_loan:
            return (
                f"Cited source {label} belongs to {loan}, "
                f"but the question is about {expected_loan}."
            )

    return None


def route_after_basic_validation(state: AgentState) -> str:
    """Continue validation, retry generation, or abstain."""

    if state.get("is_valid"):
        return "evidence_check"

    # Only citation problems can be fixed by generating again. An empty
    # retrieval would return the same nothing on a second attempt.
    if (
        state.get("failure_reason") == FAILURE_CITATION
        and state.get("attempts", 0) < MAX_ATTEMPTS
    ):
        return "retry"

    return "abstain"


# ============================================================
# NODE 6: INDEPENDENT EVIDENCE VALIDATION
# ============================================================

def evidence_validation_node(state: AgentState) -> dict:
    with agent_attempt(state.get("attempts", 0)), timed_stage("evidence_validation"):
        return _validate_evidence(state)


# Structured output makes the API enforce the verdict's JSON shape.
VALIDATION_SCHEMA = {
    "type": "object",
    "properties": {
        "supported": {"type": "boolean"},
        "identity_link_proven": {"type": "boolean"},
        "status_link_proven": {"type": "boolean"},
        "reason": {"type": "string"},
        "issues": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "supported",
        "identity_link_proven",
        "status_link_proven",
        "reason",
        "issues",
    ],
    "additionalProperties": False,
}


def build_validation_prompt(
    question: str,
    answer: str,
    sources: list[dict],
) -> str | None:
    """Build the validator prompt, or None when there is no usable evidence."""

    if not any(
        source.get("content") or source.get("text")
        for source in sources
    ):
        return None

    evidence_blocks = []

    for index, source in enumerate(sources, start=1):
        content = source.get("content") or source.get("text") or ""

        evidence_blocks.append(
            f"""
[S{index}]
Source file: {source.get('source', 'Unknown')}
Customer ID metadata: {source.get('customer_id') or 'Unknown'}
Application file (loan ID) metadata: {source.get('loan_id') or 'Unknown'}
Document type metadata: {source.get('document_type') or 'Unknown'}
Document describes: {describe_document(source.get('document_type'))}

Document content:
{str(content)[:4000]}
"""
        )

    evidence_text = "\n".join(evidence_blocks)

    return f"""
You are an independent evidence validator for a financial
document question-answering system.

Use ONLY the supplied evidence. Do not guess or use outside
knowledge.

USER QUESTION:
{question}

PROPOSED ANSWER:
{answer}

RETRIEVED EVIDENCE:
{evidence_text}

VALIDATION RULES

1. CLAIM SUPPORT
Determine whether the evidence supports every material
factual claim in the answer.

2. IDENTITY LINKAGE
For a named person, establish how that person maps to the
relevant customer or loan ID.

3. METADATA LINKAGE
The customer_id and loan_id fields in the evidence headers
are application-provided metadata. They may establish which
customer or loan a document is associated with.

Metadata can establish document association, but it does
not independently prove the truth of a factual claim in
the document content.

If a loan application names a person and identifies their
customer and loan IDs, matching IDs in another document's
metadata may establish a relationship between that person
and the second document.

If identifiers conflict, do not accept the relationship.
Do not assume metadata is trustworthy if the supplied
evidence contradicts it.

The loan ID metadata is the application file a document was
submitted with. It can link a document to a customer and an
application, but it does NOT show that a financial figure in
the document (a payment, instalment, principal, requested
amount, term or rate) belongs to that loan. Use "Document
describes" to decide which loan or agreement a figure belongs
to. A figure from a document that describes a separate
existing credit agreement does not support a claim about the
requested loan. A principal, requested amount, income figure
or existing-loan payment does not support a claim about a
monthly instalment.

4. STATUS LINKAGE
For a question about a person's or loan's status, verify:
- The document content states the status.
- The document is reliably associated with the requested
  person or loan through consistent identifiers.

The status document does not need to repeat the person's
name when reliable, consistent metadata establishes the link.

5. CITATIONS
Check whether the cited labels exist and support the claims
they accompany. Multiple chunks from one document are not
independent sources.

6. APPLICABILITY
If identity linkage is not applicable, set
identity_link_proven to true.

If status linkage is not applicable, set
status_link_proven to true.

7. FINAL DECISION
Set supported to true only when all material claims are
supported and all applicable identity and status checks pass.

If a required relationship is missing or contradictory,
set supported to false and explain why.

Return ONLY valid JSON:
{{
  "supported": false,
  "identity_link_proven": false,
  "status_link_proven": false,
  "reason": "Brief explanation",
  "issues": []
}}

All three Boolean fields must be actual JSON booleans.
The issues field must be a list of strings.
"""


def parse_validation_output(raw_output: str) -> dict:
    """Parse and strictly check the validator's JSON verdict."""

    raw_output = raw_output.strip()

    if raw_output.startswith("```"):
        raw_output = re.sub(
            r"^```(?:json)?\s*",
            "",
            raw_output,
            count=1,
            flags=re.IGNORECASE,
        )
        raw_output = re.sub(r"\s*```$", "", raw_output)

    result = json.loads(raw_output)

    for field in (
        "supported",
        "identity_link_proven",
        "status_link_proven",
    ):
        if type(result.get(field)) is not bool:
            raise ValueError(
                f"Invalid or missing Boolean field: {field}"
            )

    if not isinstance(result.get("reason"), str):
        raise ValueError("Missing or invalid reason field.")

    if not isinstance(result.get("issues"), list):
        raise ValueError("Missing or invalid issues list.")

    if not all(
        isinstance(issue, str)
        for issue in result["issues"]
    ):
        raise ValueError("Every issue must be a string.")

    return result


def run_evidence_validation(
    question: str,
    answer: str,
    sources: list[dict],
    model: str | None = None,
    reasoning_effort: str | None = None,
    structured_output: bool | None = None,
) -> dict | None:
    """
    Run the semantic evidence check with one LLM call.

    Returns the parsed verdict, or None when there is no usable evidence.
    Raises if the call fails or the verdict is malformed. Arguments left
    as None use the configured defaults.
    """
    with timed_stage("evidence_validation.prompt_prep"):
        prompt = build_validation_prompt(question, answer, sources)

    if prompt is None:
        return None

    effort = reasoning_effort or VALIDATION_REASONING_EFFORT
    use_schema = (
        VALIDATION_STRUCTURED_OUTPUT
        if structured_output is None
        else structured_output
    )

    options = llm_options(VALIDATION_MAX_OUTPUT_TOKENS, effort)

    if use_schema:
        options["text"] = {
            "format": {
                "type": "json_schema",
                "name": "evidence_validation",
                "schema": VALIDATION_SCHEMA,
                "strict": True,
            }
        }

    response = create_response(
        get_openai_client(),
        "evidence_validation",
        model=model or VALIDATION_MODEL,
        input=prompt,
        **options,
    )

    with timed_stage("evidence_validation.parse"):
        return parse_validation_output(response.output_text)


def _validate_evidence(state: AgentState) -> dict:
    """
    Independently evaluate the answer against retrieved evidence.

    Separates claim support, identity linkage, and status linkage.
    """

    try:
        result = run_evidence_validation(
            question=state["question"],
            answer=state["answer"],
            sources=state.get("sources", []),
        )

        if result is None:
            feedback = "No usable evidence text was retrieved."

            print(f"[Evidence Validator] {feedback}")

            return {
                "semantic_valid": False,
                "validation_feedback": feedback,
                "failure_reason": FAILURE_NO_EVIDENCE,
            }

        semantic_valid = (
            result["supported"]
            and result["identity_link_proven"]
            and result["status_link_proven"]
        )

        feedback = (
            f"Supported: {result['supported']}; "
            f"Identity link proven: "
            f"{result['identity_link_proven']}; "
            f"Status link proven: "
            f"{result['status_link_proven']}; "
            f"Reason: {result['reason']}; "
            f"Issues: {result['issues']}"
        )

        print(f"[Evidence Validator] Supported: {result['supported']}")
        print(f"[Evidence Validator] Identity link proven: {result['identity_link_proven']}")
        print(f"[Evidence Validator] Status link proven: {result['status_link_proven']}")
        print(f"[Evidence Validator] Reason: {result['reason']}")
        print(f"[Evidence Validator] Issues: {result['issues']}")

    except Exception as exc:
        feedback = (
            "Evidence validation failed. The answer cannot be "
            f"trusted until validation succeeds. Error: {type(exc).__name__}"
        )

        print(f"[Evidence Validator] {feedback}: {exc}")

        return {
            "semantic_valid": False,
            "validation_feedback": feedback,
            "failure_reason": FAILURE_VALIDATOR_ERROR,
        }

    if semantic_valid:
        return {
            "semantic_valid": True,
            "validation_feedback": feedback,
            "failure_reason": "",
        }

    return {
        "semantic_valid": False,
        "validation_feedback": feedback,
        "failure_reason": FAILURE_UNSUPPORTED,
        "retry_can_add_evidence": _retry_can_add_evidence(state),
    }


def _retry_can_add_evidence(state: AgentState) -> bool:
    """
    Check, without calling the LLM, whether the wider retry search
    would give the generator any chunk it has not already seen.

    Retrieval is deterministic and the query embedding is cached, so
    this costs a few milliseconds.
    """
    if state.get("attempts", 0) >= MAX_ATTEMPTS:
        return False

    with timed_stage("retry_evidence_check"):
        _, _, _, wider_sources = retrieve_evidence(
            question=state["question"],
            top_k=RETRY_TOP_K,
            analysis=_analysis_from_state(state),
        )

    def chunk_keys(sources: list[dict]) -> set[tuple]:
        return {
            (source.get("source"), source.get("chunk_index"))
            for source in sources
        }

    new_chunks = chunk_keys(wider_sources) - chunk_keys(state.get("sources", []))

    print(f"[Agent] Retry would add {len(new_chunks)} new evidence chunk(s).")

    return bool(new_chunks)


def route_after_evidence_validation(state: AgentState) -> str:
    """Finish, retry with wider retrieval, or abstain."""

    if state.get("semantic_valid"):
        return "finish"

    # A retry is only useful when the validator rejected the answer and
    # the wider search would actually supply new evidence. Validator
    # errors and missing evidence are not fixed by generating again.
    if (
        state.get("failure_reason") == FAILURE_UNSUPPORTED
        and state.get("retry_can_add_evidence")
        and state.get("attempts", 0) < MAX_ATTEMPTS
    ):
        return "retry"

    return "abstain"


# ============================================================
# NODE 7: ABSTAIN
# ============================================================


def abstain_node(state: AgentState) -> dict:
    """Return a safe response when validation does not succeed."""

    print(
        "[Agent] Unable to verify the answer after "
        "the permitted attempts."
    )

    return {
        "answer": (
            "I could not verify the answer sufficiently against "
            "the retrieved evidence. Please review the source "
            "documents or refine the question."
        ),
        "sources": [],
        "is_valid": False,
        "semantic_valid": False,
        "validation_feedback": (
            state.get("validation_feedback")
            or "Validation failed after the permitted attempts."
        ),
    }



# ============================================================
# BUILD THE LANGGRAPH WORKFLOW
# ============================================================

def _timed_node(stage: str, node):
    def wrapper(state: AgentState) -> dict:
        with timed_stage(stage):
            return node(state)

    return wrapper


def build_agent():
    graph = StateGraph(AgentState)

    graph.add_node("route_query", _timed_node("route_query", route_query))
    graph.add_node("entity_conflict", entity_conflict_node)
    graph.add_node("exact_search", exact_search_node)
    graph.add_node("answer", answer_node)
    graph.add_node("validate_basic", validate_basic_node)
    graph.add_node("evidence_check", evidence_validation_node)
    graph.add_node("abstain", abstain_node)

    graph.add_edge(START, "route_query")

    graph.add_conditional_edges(
        "route_query",
        route_search_mode,
        {
            "entity_conflict": "entity_conflict",
            "exact_search": "exact_search",
            "answer": "answer",
        },
    )

    # Conflicts are rejected without retrieval or generation.
    graph.add_edge("entity_conflict", END)

    # Exact search returns deterministic literal-search results.
    graph.add_edge("exact_search", END)

    # Semantic RAG workflow.
    graph.add_edge("answer", "validate_basic")

    graph.add_conditional_edges(
        "validate_basic",
        route_after_basic_validation,
        {
            "evidence_check": "evidence_check",
            "retry": "answer",
            "abstain": "abstain",
        },
    )

    graph.add_conditional_edges(
        "evidence_check",
        route_after_evidence_validation,
        {
            "finish": END,
            "retry": "answer",
            "abstain": "abstain",
        },
    )

    graph.add_edge("abstain", END)

    return graph.compile()


agent = build_agent()


# ============================================================
# PUBLIC ENTRY POINT
# ============================================================

def ask_agent(question: str) -> dict:
    initial_state: AgentState = {
        "question": question,
        "answer": "",
        "sources": [],
        "attempts": 0,
        "is_valid": False,
        "semantic_valid": False,
        "validation_feedback": "",
        "search_mode": "semantic",
        "exact_term": "",
        "entity_conflict": "",
        "query_analysis": {},
        "failure_reason": "",
        "retry_can_add_evidence": False,
    }

    return agent.invoke(initial_state)


# ============================================================
# COMMAND-LINE INTERFACE
# ============================================================

if __name__ == "__main__":
    question = input("Ask NexaBank: ").strip()

    result = ask_agent(question)

    print("\n" + "=" * 56)
    print("FINAL ANSWER")
    print("=" * 56)
    print(result.get("answer", ""))

    sources = result.get("sources", [])

    if sources:
        print("\nSOURCES")

        # Display each unique document only once.
        seen_sources = set()

        for source in sources:
            source_path = source.get("source", "Unknown")
            customer_id = source.get("customer_id", "Unknown")
            loan_id = source.get("loan_id", "Unknown")

            # Include identifiers in the key to avoid merging records
            # that have conflicting metadata for the same path.
            source_key = (source_path, customer_id, loan_id)

            if source_key in seen_sources:
                continue

            seen_sources.add(source_key)

            print(
                f"- {source_path} "
                f"(customer={customer_id}, loan={loan_id})"
            )

    print(f"\nSearch mode: {result.get('search_mode', 'unknown')}")
    print(f"Attempts: {result.get('attempts', 0)}")
    print(
        f"Basic validation passed: "
        f"{result.get('is_valid', False)}"
    )
    print(
        f"Evidence validation passed: "
        f"{result.get('semantic_valid', False)}"
    )

    if result.get("validation_feedback"):
        print(
            f"Validation feedback: "
            f"{result['validation_feedback']}"
        )
