import json
import os
from types import SimpleNamespace

import pytest

# The tests never call OpenAI; a placeholder key lets the SDK client be built.
os.environ.setdefault("OPENAI_API_KEY", "test-placeholder-key")


class FakeResponses:
    def __init__(self, owner: "FakeOpenAI"):
        self.owner = owner

    def create(self, **kwargs):
        self.owner.calls.append(kwargs)
        prompt = kwargs["input"]

        if "independent evidence validator" in prompt:
            self.owner.validation_calls += 1
            output = self.owner.validator(prompt)
        else:
            self.owner.generation_calls += 1
            output = self.owner.generator(prompt)

        if isinstance(output, Exception):
            raise output

        return SimpleNamespace(
            output_text=output,
            usage=SimpleNamespace(
                input_tokens=100,
                output_tokens=20,
                output_tokens_details=SimpleNamespace(reasoning_tokens=5),
            ),
        )


class FakeOpenAI:
    """Stands in for the OpenAI client; behaviour is set per test."""

    def __init__(self):
        self.calls = []
        self.generation_calls = 0
        self.validation_calls = 0
        self.generator = lambda prompt: "The value is EUR 1 [S1]."
        self.validator = lambda prompt: verdict(True)
        self.responses = FakeResponses(self)


def verdict(supported: bool, reason: str = "test") -> str:
    return json.dumps(
        {
            "supported": supported,
            "identity_link_proven": True,
            "status_link_proven": True,
            "reason": reason,
            "issues": [] if supported else ["not supported"],
        }
    )


@pytest.fixture
def fake_llm(monkeypatch):
    fake = FakeOpenAI()

    import src.agents.rag_agent as rag_agent
    import src.rag.answer_question as answer_module

    monkeypatch.setattr(rag_agent, "get_openai_client", lambda: fake)
    monkeypatch.setattr(answer_module, "get_openai_client", lambda: fake)

    return fake
