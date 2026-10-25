"""
Agent routing, retry and abstention behaviour, with retrieval and the
LLM replaced by fakes so every path is deterministic.
"""

import pytest

import src.agents.rag_agent as rag_agent
from src.retrieval.query_analyzer import QueryAnalysis
from tests.conftest import verdict


def source(index: int, chunk_index: int = 0) -> dict:
    return {
        "source_id": f"S{index}",
        "source": f"data/raw/NB-LOAN-2101/pdf/0{index}_doc.pdf",
        "document_type": "payslip",
        "loan_id": "NB-LOAN-2101",
        "customer_id": "NB-CUST-3001",
        "chunk_index": chunk_index,
        "similarity": 0.8,
        "content": "Gross monthly salary: EUR 6,000.00",
    }


class FakeRetrieval:
    """Replaces answer_question / retrieve_evidence in the agent module."""

    def __init__(self, fake_llm, sources_by_top_k: dict[int, list[dict]]):
        self.fake_llm = fake_llm
        self.sources_by_top_k = sources_by_top_k
        self.answer_calls: list[dict] = []
        self.retrieve_calls: list[dict] = []

    def answer_question(self, question, top_k=5, analysis=None):
        self.answer_calls.append({"top_k": top_k, "analysis": analysis})
        sources = self.sources_by_top_k.get(top_k, [])

        if not sources:
            return {"question": question, "answer": "No documents.", "sources": []}

        answer = self.fake_llm.responses.create(input=f"QUESTION {question}").output_text
        return {"question": question, "answer": answer, "sources": sources}

    def retrieve_evidence(self, question, top_k=5, analysis=None):
        self.retrieve_calls.append({"top_k": top_k, "analysis": analysis})
        sources = self.sources_by_top_k.get(top_k, [])
        return [], analysis, "context" if sources else "", sources


@pytest.fixture
def retrieval(monkeypatch, fake_llm):
    def install(sources_by_top_k):
        fake = FakeRetrieval(fake_llm, sources_by_top_k)
        monkeypatch.setattr(rag_agent, "answer_question", fake.answer_question)
        monkeypatch.setattr(rag_agent, "retrieve_evidence", fake.retrieve_evidence)
        return fake

    return install


QUESTION = "What is Lotte van Dijk's monthly gross salary?"


def test_conflict_stops_before_retrieval_and_llm(retrieval, fake_llm):
    fake = retrieval({5: [source(1)]})

    result = rag_agent.ask_agent(
        "Does the credit analyst note for loan NB-LOAN-2101 confirm that "
        "Thomas de Boer's document review is pending?"
    )

    assert result["search_mode"] == "conflict"
    assert "identifiers conflict" in result["answer"]
    assert result["sources"] == []
    assert result["semantic_valid"] is False
    assert fake.answer_calls == []
    assert fake_llm.calls == []


def test_supported_answer_finishes_in_one_attempt(retrieval, fake_llm):
    fake = retrieval({5: [source(1)]})

    result = rag_agent.ask_agent(QUESTION)

    assert result["attempts"] == 1
    assert result["is_valid"] is True
    assert result["semantic_valid"] is True
    assert result["answer"] == "The value is EUR 1 [S1]."
    assert fake_llm.validation_calls == 1
    assert len(fake.answer_calls) == 1


def test_route_query_analysis_is_reused_for_retrieval(retrieval):
    fake = retrieval({5: [source(1)]})

    rag_agent.ask_agent(QUESTION)

    analysis = fake.answer_calls[0]["analysis"]
    assert isinstance(analysis, QueryAnalysis)
    assert analysis.customer_id == "NB-CUST-3001"
    assert analysis.document_type == "payslip"


def test_missing_citations_retry_is_bounded(retrieval, fake_llm):
    retrieval({5: [source(1)], 8: [source(1)]})
    fake_llm.generator = lambda prompt: "An answer without any citation."

    result = rag_agent.ask_agent(QUESTION)

    assert result["attempts"] == rag_agent.MAX_ATTEMPTS == 2
    assert fake_llm.generation_calls == 2
    assert fake_llm.validation_calls == 0
    assert result["semantic_valid"] is False
    assert result["sources"] == []
    assert "could not verify" in result["answer"]


def test_no_evidence_abstains_without_retry(retrieval, fake_llm):
    fake = retrieval({})

    result = rag_agent.ask_agent(QUESTION)

    assert result["attempts"] == 1
    assert len(fake.answer_calls) == 1
    assert fake_llm.calls == []
    assert result["semantic_valid"] is False


def test_unsupported_answer_without_new_evidence_does_not_retry(retrieval, fake_llm):
    fake = retrieval({5: [source(1)], 8: [source(1)]})
    fake_llm.validator = lambda prompt: verdict(False)

    result = rag_agent.ask_agent(QUESTION)

    assert result["attempts"] == 1
    assert fake_llm.generation_calls == 1
    assert fake_llm.validation_calls == 1
    assert [call["top_k"] for call in fake.retrieve_calls] == [rag_agent.RETRY_TOP_K]
    assert result["semantic_valid"] is False
    assert "could not verify" in result["answer"]


def test_unsupported_answer_retries_once_when_wider_search_adds_evidence(retrieval, fake_llm):
    fake = retrieval({5: [source(1)], 8: [source(1), source(2)]})
    fake_llm.validator = lambda prompt: verdict(False)

    result = rag_agent.ask_agent(QUESTION)

    assert result["attempts"] == 2
    assert [call["top_k"] for call in fake.answer_calls] == [5, 8]
    assert fake_llm.generation_calls == 2
    assert fake_llm.validation_calls == 2
    assert result["semantic_valid"] is False


def test_retry_can_succeed(retrieval, fake_llm):
    retrieval({5: [source(1)], 8: [source(1), source(2)]})
    verdicts = iter([verdict(False), verdict(True)])
    fake_llm.validator = lambda prompt: next(verdicts)

    result = rag_agent.ask_agent(QUESTION)

    assert result["attempts"] == 2
    assert result["semantic_valid"] is True
    assert result["sources"]


@pytest.mark.parametrize(
    "validator_output",
    [RuntimeError("validator unavailable"), "not json", '{"supported": "yes"}'],
)
def test_validator_failure_abstains_without_regenerating(retrieval, fake_llm, validator_output):
    retrieval({5: [source(1)], 8: [source(1), source(2)]})
    fake_llm.validator = lambda prompt: validator_output

    result = rag_agent.ask_agent(QUESTION)

    assert result["attempts"] == 1
    assert fake_llm.generation_calls == 1
    assert result["semantic_valid"] is False
    assert result["sources"] == []
    assert "Evidence validation failed" in result["validation_feedback"]


def test_generation_error_propagates(retrieval, fake_llm):
    retrieval({5: [source(1)]})
    fake_llm.generator = lambda prompt: TimeoutError("LLM timed out")

    with pytest.raises(TimeoutError):
        rag_agent.ask_agent(QUESTION)
