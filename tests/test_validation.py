"""Deterministic validation checks and the evidence validator's plumbing."""

import pytest
from fastapi.testclient import TestClient

import src.agents.rag_agent as rag_agent
import src.api.main as api
from tests.conftest import verdict


def state_with(answer: str, sources: list[dict], customer_id=None, loan_id=None) -> dict:
    return {
        "question": "q",
        "answer": answer,
        "sources": sources,
        "attempts": 1,
        "query_analysis": {"customer_id": customer_id, "loan_id": loan_id},
    }


def source(label: str, customer="NB-CUST-3001", loan="NB-LOAN-2101", document_type="payslip"):
    return {
        "source_id": label,
        "source": "data/raw/NB-LOAN-2101/pdf/03_payslip.pdf",
        "document_type": document_type,
        "customer_id": customer,
        "loan_id": loan,
        "content": "Net salary: EUR 4,300.00",
    }


def test_cited_source_from_another_customer_fails_before_llm():
    state = state_with(
        "Net salary is EUR 4,300 [S1].",
        [source("S1", customer="NB-CUST-3002")],
        customer_id="NB-CUST-3001",
    )

    result = rag_agent.validate_basic_node(state)

    assert result["is_valid"] is False
    assert result["failure_reason"] == rag_agent.FAILURE_CITATION
    assert "NB-CUST-3002" in result["validation_feedback"]


def test_cited_source_from_another_loan_fails():
    state = state_with(
        "Term is 48 months [S1].",
        [source("S1", loan="NB-LOAN-2102")],
        loan_id="NB-LOAN-2101",
    )

    assert rag_agent.validate_basic_node(state)["is_valid"] is False


def test_uncited_mismatching_source_is_not_flagged():
    state = state_with(
        "Net salary is EUR 4,300 [S1].",
        [source("S1"), source("S2", customer="NB-CUST-3002")],
        customer_id="NB-CUST-3001",
    )

    assert rag_agent.validate_basic_node(state)["is_valid"] is True


def test_source_without_ids_is_left_to_the_evidence_validator():
    state = state_with(
        "Net salary is EUR 4,300 [S1].",
        [source("S1", customer=None, loan=None, document_type="csv_record")],
        customer_id="NB-CUST-3001",
    )

    assert rag_agent.validate_basic_node(state)["is_valid"] is True


def test_cited_source_missing_document_type_fails():
    state = state_with("Net salary is EUR 4,300 [S1].", [source("S1", document_type=None)])

    assert rag_agent.validate_basic_node(state)["is_valid"] is False


def test_validator_uses_one_call_with_configured_options(fake_llm):
    result = rag_agent.run_evidence_validation("q", "a [S1]", [source("S1")])

    assert result["supported"] is True
    assert fake_llm.validation_calls == 1
    call = fake_llm.calls[0]
    assert call["reasoning"] == {"effort": rag_agent.VALIDATION_REASONING_EFFORT}
    assert call["max_output_tokens"] == int(rag_agent.VALIDATION_MAX_OUTPUT_TOKENS)
    assert "text" not in call


def test_validator_structured_output_option(fake_llm):
    rag_agent.run_evidence_validation("q", "a [S1]", [source("S1")], structured_output=True)

    assert fake_llm.calls[0]["text"]["format"]["type"] == "json_schema"


def test_validator_returns_none_without_evidence_text(fake_llm):
    empty = dict(source("S1"), content="")

    assert rag_agent.run_evidence_validation("q", "a", [empty]) is None
    assert fake_llm.calls == []


@pytest.mark.parametrize("raw", ["```json\n" + verdict(False) + "\n```", verdict(True)])
def test_parse_accepts_fenced_and_plain_json(raw):
    assert isinstance(rag_agent.parse_validation_output(raw)["supported"], bool)


def test_dev_validate_endpoint_hidden_in_production(monkeypatch):
    monkeypatch.setattr(api, "EXPOSE_TIMINGS", False)
    client = TestClient(api.app)

    response = client.post(
        "/dev/validate",
        json={"question": "q", "answer": "a", "sources": []},
    )

    assert response.status_code == 404


def test_dev_validate_endpoint_reports_verdict_and_timings(fake_llm):
    client = TestClient(api.app)

    body = client.post(
        "/dev/validate",
        json={
            "question": "q",
            "answer": "a [S1]",
            "sources": [{"source": "f.pdf", "content": "text"}],
            "reasoning_effort": "minimal",
        },
    ).json()

    assert body["verdict"]["supported"] is True
    assert "evidence_validation" in body["timings_ms"]
    assert fake_llm.calls[0]["reasoning"] == {"effort": "minimal"}
