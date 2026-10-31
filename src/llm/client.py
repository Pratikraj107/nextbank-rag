"""
Shared OpenAI client.

Creating one client per process (instead of one per call) reuses HTTP
connections and avoids repeated TLS handshakes. The client is created
lazily so importing the agent does not require OPENAI_API_KEY.
"""

import os
import threading

from openai import OpenAI

# Per-call timeout in seconds. The SDK also retries transient failures.
OPENAI_TIMEOUT_SECONDS = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "60"))

_client: OpenAI | None = None
_lock = threading.Lock()


def get_openai_client() -> OpenAI:
    global _client

    if _client is None:
        with _lock:
            if _client is None:
                _client = OpenAI(timeout=OPENAI_TIMEOUT_SECONDS)

    return _client


def create_response(client, stage: str, **kwargs):
    """
    Call the Responses API and record detailed timings for `stage`:

      <stage>.llm_request        client wall time: send, wait, receive
      <stage>.server_processing  time OpenAI reports spending on the request
                                 (header `openai-processing-ms`); the gap to
                                 llm_request is network and queueing overhead
      <stage>.sdk_retries        only recorded when the SDK retried

    Token usage is recorded under `stage`.
    """
    # Imported here to keep this module free of import cycles.
    from src.observability.timing import (
        record_duration,
        record_llm_usage,
        timed_stage,
    )

    raw_api = getattr(client.responses, "with_raw_response", None)
    processing_ms = None
    retries = 0

    with timed_stage(f"{stage}.llm_request"):
        if raw_api is not None:
            raw = raw_api.create(**kwargs)
            response = raw.parse()
            processing_ms = raw.headers.get("openai-processing-ms")
            retries = getattr(raw, "retries_taken", 0) or 0
        else:
            response = client.responses.create(**kwargs)

    if processing_ms is not None:
        try:
            record_duration(f"{stage}.server_processing", float(processing_ms))
        except ValueError:
            pass

    if retries:
        record_duration(f"{stage}.sdk_retries", float(retries))

    record_llm_usage(stage, response)

    return response
