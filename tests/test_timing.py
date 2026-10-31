import pytest

from src.observability.timing import (
    agent_attempt,
    end_request_timer,
    start_request_timer,
    timed_stage,
)


def test_stages_are_recorded_with_attempt_prefix():
    timer, token = start_request_timer()
    try:
        with timed_stage("route_query"):
            pass
        with agent_attempt(2), timed_stage("answer_generation"):
            pass
    finally:
        end_request_timer(token)

    summary = timer.summary()

    assert "route_query" in summary
    assert "attempt_2.answer_generation" in summary
    assert summary["total"] >= 0


def test_failed_stage_is_still_recorded():
    timer, token = start_request_timer()
    try:
        with pytest.raises(ValueError):
            with timed_stage("evidence_validation"):
                raise ValueError("boom")
    finally:
        end_request_timer(token)

    [stage] = timer.stages
    assert stage.stage == "evidence_validation"
    assert stage.status == "error"
    assert stage.error_type == "ValueError"


def test_no_timer_means_no_recording():
    with timed_stage("anything"):
        value = 1

    assert value == 1
