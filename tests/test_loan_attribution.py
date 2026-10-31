"""
Regression tests for loan-figure attribution.

Failure fixed: "What is the monthly instalment for loan NB-LOAN-2101?" was
answered with EUR 310, the monthly payment of the customer's separate
existing loan, because that statement is filed under application
NB-LOAN-2101 and its header said "Loan ID: NB-LOAN-2101".

NB-LOAN-9001 below is an isolated synthetic fixture: no real document
states a monthly instalment, so a positive case needs its own data.
"""

import pytest

import src.agents.rag_agent as rag_agent
from src.rag.answer_question import assemble_context
from src.rag.document_subjects import describe_document
from tests.conftest import verdict

EXISTING_STATEMENT = {
    "source_id": "S1",
    "source": "data/raw/NB-LOAN-2101/pdf/06_existing_loan_statement.pdf",
    "document_type": "existing_loan_statement",
    "customer_id": "NB-CUST-3001",
    "loan_id": "NB-LOAN-2101",
    "chunk_index": 1,
    "content": "balance: EUR 4,820 Monthly payment: EUR 310 Statement date: 30-09-2026",
}

LOAN_OFFER_2101 = {
    "source_id": "S2",
    "source": "data/raw/NB-LOAN-2101/pdf/08_loan_offer.pdf",
    "document_type": "loan_offer",
    "customer_id": "NB-CUST-3001",
    "loan_id": "NB-LOAN-2101",
    "chunk_index": 0,
    "content": "Loan reference: NB-LOAN-2101 Principal: EUR 22,000 Term: 48 months",
}

# Synthetic fixture: an offer that does state an instalment.
FIXTURE_OFFER_9001 = {
    "source_id": "S1",
    "source": "tests/fixtures/NB-LOAN-9001/08_loan_offer.pdf",
    "document_type": "loan_offer",
    "customer_id": "NB-CUST-9001",
    "loan_id": "NB-LOAN-9001",
    "chunk_index": 0,
    "content": "Loan reference: NB-LOAN-9001 Principal: EUR 20,000 Term: 48 months "
               "Monthly instalment: EUR 512.40",
}


def state(question, answer, sources):
    analysis = rag_agent.QueryAnalyzer().analyze(question).to_dict()
    return {
        "question": question,
        "answer": answer,
        "sources": sources,
        "attempts": 1,
        "query_analysis": analysis,
    }


# ------------------------------------------------------------
# Deterministic attribution guard (basic validation)
# ------------------------------------------------------------

def test_original_failure_is_rejected_before_llm_validation():
    s = state(
        "What is the monthly instalment for loan NB-LOAN-2101?",
        "The monthly instalment is EUR 310 (per the loan statement) [S1].",
        [EXISTING_STATEMENT],
    )

    result = rag_agent.validate_basic_node(s)

    assert result["is_valid"] is False
    assert "separate existing credit agreement" in result["validation_feedback"]


@pytest.mark.parametrize(
    "question",
    [
        "What is the monthly repayment for NB-LOAN-2102?",
        "What is the principal of loan NB-LOAN-2103?",
        "What is the interest rate on NB-LOAN-2101?",
    ],
)
def test_existing_loan_figures_never_answer_a_named_loans_terms(question):
    source = dict(EXISTING_STATEMENT, loan_id="NB-LOAN-2101")
    s = state(question, "It is EUR 310 [S1].", [source])

    assert rag_agent.validate_basic_node(s)["is_valid"] is False


def test_question_about_the_existing_loan_may_cite_its_statement():
    s = state(
        "What is the monthly payment on the existing loan in application NB-LOAN-2101?",
        "The existing loan's monthly payment is EUR 310 [S1].",
        [EXISTING_STATEMENT],
    )

    assert rag_agent.validate_basic_node(s)["is_valid"] is True


def test_documented_instalment_for_the_right_loan_still_passes():
    s = state(
        "What is the monthly instalment for loan NB-LOAN-9001?",
        "The monthly instalment for NB-LOAN-9001 is EUR 512.40 [S1].",
        [FIXTURE_OFFER_9001],
    )

    assert rag_agent.validate_basic_node(s)["is_valid"] is True


def test_mixed_citations_are_left_to_the_evidence_validator():
    s = state(
        "What is the monthly instalment for loan NB-LOAN-2101?",
        "Unclear [S1][S2].",
        [EXISTING_STATEMENT, LOAN_OFFER_2101],
    )

    assert rag_agent.validate_basic_node(s)["is_valid"] is True


def test_questions_without_a_loan_id_are_not_affected():
    s = state(
        "What is Lotte van Dijk's monthly net salary?",
        "EUR 4,300 [S1].",
        [dict(EXISTING_STATEMENT, document_type="payslip")],
    )

    assert rag_agent.validate_basic_node(s)["is_valid"] is True


# ------------------------------------------------------------
# Evidence headers tell both LLM steps what each document describes
# ------------------------------------------------------------

def test_existing_statement_is_described_as_a_separate_agreement():
    assert "NOT the requested loan" in describe_document("existing_loan_statement")
    assert "requested loan" in describe_document("loan_offer")
    assert describe_document("unknown_type") == "not specified"


def test_validator_prompt_explains_application_file_and_subject():
    prompt = rag_agent.build_validation_prompt(
        "What is the monthly instalment for loan NB-LOAN-2101?",
        "EUR 310 [S1]",
        [EXISTING_STATEMENT],
    )

    assert "Application file (loan ID) metadata: NB-LOAN-2101" in prompt
    assert "Document describes: a separate existing credit agreement" in prompt
    assert "does NOT show that a financial figure" in prompt
    assert "does not support a claim about a\nmonthly instalment" in prompt
    assert "Loan ID metadata:" not in prompt


def test_generation_context_explains_application_file_and_subject():
    context, sources = assemble_context(
        [{"score": 0.9, "chunk": EXISTING_STATEMENT}, {"score": 0.8, "chunk": LOAN_OFFER_2101}]
    )

    assert "Application file (loan ID): NB-LOAN-2101" in context
    assert "Document describes: a separate existing credit agreement" in context
    assert "Document describes: the requested loan" in context
    # Citation labels still map, in order, to the returned sources.
    assert [s["source_id"] for s in sources] == ["S1", "S2"]
    assert sources[0]["source"] == EXISTING_STATEMENT["source"]


# ------------------------------------------------------------
# Whole agent, with retrieval and the LLM faked
# ------------------------------------------------------------

def run_agent(monkeypatch, fake_llm, question, sources, answers):
    replies = iter(answers)

    def fake_answer_question(question, top_k=5, analysis=None):
        return {"question": question, "answer": next(replies), "sources": sources}

    monkeypatch.setattr(rag_agent, "answer_question", fake_answer_question)
    return rag_agent.ask_agent(question)


def test_agent_abstains_when_only_existing_loan_evidence_is_cited(monkeypatch, fake_llm):
    result = run_agent(
        monkeypatch, fake_llm,
        "What is the monthly instalment for loan NB-LOAN-2101?",
        [EXISTING_STATEMENT],
        ["The monthly instalment is EUR 310 [S1].", "It is EUR 310 [S1]."],
    )

    assert result["attempts"] == 2  # one bounded retry, then abstain
    assert result["semantic_valid"] is False
    assert result["sources"] == []
    assert "could not verify" in result["answer"]
    assert fake_llm.validation_calls == 0


def test_agent_accepts_the_retry_when_it_declines_correctly(monkeypatch, fake_llm):
    result = run_agent(
        monkeypatch, fake_llm,
        "What is the monthly instalment for loan NB-LOAN-2101?",
        [EXISTING_STATEMENT, LOAN_OFFER_2101],
        [
            "The monthly instalment is EUR 310 [S1].",
            "The documents do not confirm the monthly instalment for NB-LOAN-2101 [S2].",
        ],
    )

    # S1 alone is an existing-loan citation; the second answer cites the offer.
    assert result["attempts"] == 2
    assert result["semantic_valid"] is True
    assert "do not confirm" in result["answer"]


def test_agent_answers_documented_instalment_for_fixture_loan(monkeypatch, fake_llm):
    result = run_agent(
        monkeypatch, fake_llm,
        "What is the monthly instalment for loan NB-LOAN-9001?",
        [FIXTURE_OFFER_9001],
        ["The monthly instalment for NB-LOAN-9001 is EUR 512.40 [S1]."],
    )

    assert result["attempts"] == 1
    assert result["semantic_valid"] is True
    assert "512.40" in result["answer"]


def test_conflict_still_stops_before_generation(monkeypatch, fake_llm):
    result = run_agent(
        monkeypatch, fake_llm,
        "For customer NB-CUST-3002, what is the monthly instalment of NB-LOAN-2101?",
        [EXISTING_STATEMENT],
        ["should never be generated"],
    )

    assert result["search_mode"] == "conflict"
    assert fake_llm.calls == []
