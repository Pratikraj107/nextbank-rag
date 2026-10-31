"""API error handling and the development-only timing fields."""

import httpx
import openai
import pytest
from fastapi.testclient import TestClient

import src.api.main as api


@pytest.fixture
def client():
    # Not used as a context manager, so the startup warm-up does not run.
    return TestClient(api.app, raise_server_exceptions=False)


def agent_result(**overrides):
    result = {
        "answer": "Salary is EUR 72,000 [S1].",
        "sources": [
            {
                "source": "data/raw/NB-LOAN-2101/docx/09_employment_agreement.docx",
                "document_type": "employment_agreement",
                "customer_id": "NB-CUST-3001",
                "loan_id": "NB-LOAN-2101",
                "chunk_index": 0,
            }
        ],
        "search_mode": "semantic",
        "attempts": 1,
        "is_valid": True,
        "semantic_valid": True,
    }
    result.update(overrides)
    return result


def test_success_response_keeps_contract_and_adds_timings(client, monkeypatch):
    monkeypatch.setattr(api, "ask_agent", lambda question: agent_result())

    response = client.post("/api/chat", json={"question": "Annual salary?"})

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Salary is EUR 72,000 [S1]."
    assert body["sources"][0]["loan_id"] == "NB-LOAN-2101"
    assert body["basic_validation_passed"] is True
    assert body["evidence_validation_passed"] is True
    assert "total" in body["timings_ms"]
    assert "agent_total" in body["timings_ms"]
    assert response.headers["X-Request-ID"]


def test_timings_hidden_in_production(client, monkeypatch):
    monkeypatch.setattr(api, "ask_agent", lambda question: agent_result())
    monkeypatch.setattr(api, "EXPOSE_TIMINGS", False)

    body = client.post("/api/chat", json={"question": "Annual salary?"}).json()

    assert body["timings_ms"] is None
    assert body["token_usage"] is None


@pytest.mark.parametrize(
    "error",
    [
        openai.APITimeoutError(request=httpx.Request("POST", "https://api.openai.com")),
        RuntimeError("boom"),
    ],
)
def test_errors_return_500_without_validation_status(client, monkeypatch, error):
    def fail(question):
        raise error

    monkeypatch.setattr(api, "ask_agent", fail)

    response = client.post("/api/chat", json={"question": "Annual salary?"})

    assert response.status_code == 500
    assert response.json() == {"detail": "The assistant could not process your question."}
    assert response.headers["X-Request-ID"]


def test_blank_question_rejected(client):
    response = client.post("/api/chat", json={"question": "   "})

    assert response.status_code == 422
