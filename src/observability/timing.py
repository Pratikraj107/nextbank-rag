"""
Per-request stage timing.

A `RequestTimer` is bound to the current request through a context
variable, so pipeline code can record stages with `timed_stage(...)`
without passing the timer around. Outside a request (CLI scripts,
evaluation), `timed_stage` records nothing and only runs the block.

Only stage names, durations, attempt numbers and exception types are
logged — never question text, document content or credentials.
"""

import json
import logging
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Iterator

logger = logging.getLogger("nexabank.timing")

_current_timer: ContextVar["RequestTimer | None"] = ContextVar(
    "nexabank_request_timer",
    default=None,
)


@dataclass
class StageTiming:
    stage: str
    duration_ms: float
    attempt: int | None = None
    status: str = "ok"
    error_type: str | None = None


@dataclass
class RequestTimer:
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    started_at: float = field(default_factory=time.perf_counter)
    stages: list[StageTiming] = field(default_factory=list)
    # LLM token counts per stage, e.g. {"attempt_1.answer_generation": {...}}.
    token_usage: dict[str, dict[str, int]] = field(default_factory=dict)

    def record(self, timing: StageTiming) -> None:
        self.stages.append(timing)

        logger.info(
            json.dumps(
                {
                    "event": "stage",
                    "request_id": self.request_id,
                    "stage": timing.stage,
                    "attempt": timing.attempt,
                    "duration_ms": round(timing.duration_ms, 1),
                    "status": timing.status,
                    "error_type": timing.error_type,
                }
            )
        )

    def record_tokens(self, stage: str, usage: dict[str, int]) -> None:
        attempt = _current_attempt.get()
        key = f"attempt_{attempt}.{stage}" if attempt is not None else stage
        self.token_usage[key] = usage

        logger.info(
            json.dumps(
                {
                    "event": "llm_usage",
                    "request_id": self.request_id,
                    "stage": stage,
                    "attempt": attempt,
                    **usage,
                }
            )
        )

    def total_ms(self) -> float:
        return (time.perf_counter() - self.started_at) * 1000

    def summary(self) -> dict[str, float]:
        """
        Aggregate durations by stage. Stages recorded inside an agent
        attempt are prefixed, e.g. "attempt_1.answer_generation".
        """
        totals: dict[str, float] = {}

        for timing in self.stages:
            key = (
                f"attempt_{timing.attempt}.{timing.stage}"
                if timing.attempt is not None
                else timing.stage
            )
            totals[key] = totals.get(key, 0.0) + timing.duration_ms

        totals["total"] = self.total_ms()

        return {key: round(value, 1) for key, value in totals.items()}

    def log_summary(self, status: str) -> None:
        logger.info(
            json.dumps(
                {
                    "event": "request_complete",
                    "request_id": self.request_id,
                    "status": status,
                    "timings_ms": self.summary(),
                }
            )
        )


def start_request_timer() -> tuple[RequestTimer, object]:
    """Bind a new timer to the current context. Returns (timer, reset token)."""
    timer = RequestTimer()
    token = _current_timer.set(timer)
    return timer, token


def end_request_timer(token: object) -> None:
    _current_timer.reset(token)  # type: ignore[arg-type]


def current_timer() -> RequestTimer | None:
    return _current_timer.get()


def record_duration(stage: str, duration_ms: float) -> None:
    """Record a duration measured elsewhere (e.g. reported by a server)."""
    timer = _current_timer.get()

    if timer is not None:
        timer.record(
            StageTiming(
                stage=stage,
                duration_ms=duration_ms,
                attempt=_current_attempt.get(),
            )
        )


def record_llm_usage(stage: str, response: object) -> None:
    """Record token counts from an OpenAI Responses API result, if available."""
    timer = _current_timer.get()
    usage = getattr(response, "usage", None)

    if timer is None or usage is None:
        return

    details = getattr(usage, "output_tokens_details", None)

    timer.record_tokens(
        stage,
        {
            "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
            "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
            "reasoning_tokens": int(getattr(details, "reasoning_tokens", 0) or 0),
        },
    )


_current_attempt: ContextVar[int | None] = ContextVar(
    "nexabank_agent_attempt",
    default=None,
)


@contextmanager
def agent_attempt(attempt: int) -> Iterator[None]:
    """Tag stages recorded inside this block with an attempt number."""
    token = _current_attempt.set(attempt)
    try:
        yield
    finally:
        _current_attempt.reset(token)


@contextmanager
def timed_stage(stage: str) -> Iterator[None]:
    """
    Time a block and record it on the current request timer.

    The duration is recorded even when the block raises, with the
    exception type, so failed requests still show where time went.
    """
    timer = _current_timer.get()

    if timer is None:
        yield
        return

    started = time.perf_counter()
    status = "ok"
    error_type = None

    try:
        yield
    except BaseException as exc:
        status = "error"
        error_type = type(exc).__name__
        raise
    finally:
        timer.record(
            StageTiming(
                stage=stage,
                duration_ms=(time.perf_counter() - started) * 1000,
                attempt=_current_attempt.get(),
                status=status,
                error_type=error_type,
            )
        )
