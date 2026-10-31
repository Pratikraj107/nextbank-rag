import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from typing import Literal

from pydantic import BaseModel, Field

from src.agents.rag_agent import ask_agent, run_evidence_validation
from src.api.documents import get_document_library
from src.api.documents import router as documents_router
from src.api.uploads import get_ingestion_service
from src.api.uploads import router as uploads_router
from src.documents.library import DocumentLibraryError
from src.embeddings.semantic_search import warm_up
from src.observability.timing import (
    end_request_timer,
    start_request_timer,
    timed_stage,
)

# Stage timings are only returned to clients outside production.
EXPOSE_TIMINGS = os.getenv("NEXABANK_ENV", "development").lower() != "production"

timing_logger = logging.getLogger("nexabank.timing")

if not timing_logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    timing_logger.addHandler(handler)
    timing_logger.setLevel(logging.INFO)
    timing_logger.propagate = False

@asynccontextmanager
async def lifespan(_: FastAPI):
    # Load the embedding model and chunk embeddings once, before the
    # first request, instead of paying for it inside a user's request.
    started = time.perf_counter()
    warm_up()
    timing_logger.info(
        '{"event": "startup_warm_up", "duration_ms": %.1f}',
        (time.perf_counter() - started) * 1000,
    )

    # Load the document library early so data problems show up in the
    # logs at startup. Chat keeps working if it fails; the document
    # endpoints then return 503 with the reason.
    try:
        documents = get_document_library().all()
        timing_logger.info('{"event": "document_library_loaded", "documents": %d}', len(documents))
    except DocumentLibraryError as exc:
        timing_logger.warning('{"event": "document_library_unavailable", "reason": "%s"}', exc)

    # Load upload job records: jobs interrupted by a restart are marked
    # failed, and "ready" jobs whose document left the index are flagged.
    get_ingestion_service().reconcile()

    yield


app = FastAPI(
    title="NexaBank Loan Intelligence API",
    description="API for the NexaBank document intelligence assistant",
    version="0.1.0",
    lifespan=lifespan,
)

# Local frontend development only.
# Restrict this to your deployed frontend origin before production.
# Uploads first: /api/documents/upload-options must not be read as a document ID.
app.include_router(uploads_router)
app.include_router(documents_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class SourceResponse(BaseModel):
    source: str = "Unknown"
    document_type: str = "unknown"
    customer_id: str | None = None
    loan_id: str | None = None
    chunk_index: int | None = None


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceResponse]
    search_mode: str
    attempts: int
    basic_validation_passed: bool
    evidence_validation_passed: bool
    # Development only: per-stage durations in milliseconds.
    timings_ms: dict[str, float] | None = None
    # Development only: LLM token counts per stage.
    token_usage: dict[str, dict[str, int]] | None = None


@app.get("/health")
def health_check():
    return {"status": "ok", "service": "nexabank-api"}


@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest, response: Response):
    question = request.question.strip()

    if not question:
        raise HTTPException(
            status_code=422,
            detail="Question cannot be empty.",
        )

    timer, token = start_request_timer()
    response.headers["X-Request-ID"] = timer.request_id
    status = "error"

    try:
        with timed_stage("agent_total"):
            result = ask_agent(question)

        # Return only metadata, not entire document chunks.
        sources = [
            SourceResponse(
                source=s.get("source", "Unknown"),
                document_type=s.get("document_type", "unknown"),
                customer_id=s.get("customer_id"),
                loan_id=s.get("loan_id"),
                chunk_index=s.get("chunk_index"),
            )
            for s in result.get("sources", [])
        ]

        status = "ok"

        return ChatResponse(
            timings_ms=timer.summary() if EXPOSE_TIMINGS else None,
            token_usage=timer.token_usage if EXPOSE_TIMINGS else None,
            answer=result.get("answer", ""),
            sources=sources,
            search_mode=result.get("search_mode", "unknown"),
            attempts=result.get("attempts", 0),
            basic_validation_passed=result.get("is_valid", False),
            evidence_validation_passed=result.get(
                "semantic_valid", False
            ),
        )

    except Exception as exc:
        print(f"[API Error] {type(exc).__name__}: {exc}")
        raise HTTPException(
            status_code=500,
            detail="The assistant could not process your question.",
            headers={"X-Request-ID": timer.request_id},
        ) from exc

    finally:
        timer.log_summary(status)
        end_request_timer(token)


# ============================================================
# DEVELOPMENT ONLY: evidence-validator benchmark endpoint
# ============================================================

class DevValidationSource(BaseModel):
    source: str
    document_type: str | None = None
    customer_id: str | None = None
    loan_id: str | None = None
    chunk_index: int | None = None
    content: str


class DevValidationRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    answer: str = Field(min_length=1, max_length=8000)
    sources: list[DevValidationSource] = Field(max_length=20)
    model: str | None = Field(default=None, pattern=r"^gpt-[A-Za-z0-9.\-]+$")
    reasoning_effort: Literal["minimal", "low", "medium", "high"] | None = None
    structured_output: bool | None = None


@app.post("/dev/validate", include_in_schema=False)
def dev_validate(request: DevValidationRequest, response: Response):
    """
    Run only the evidence validator, optionally with a different model,
    reasoning effort or output format, so validator settings can be
    benchmarked against known-good and known-bad answers.
    Not available when NEXABANK_ENV=production.
    """
    if not EXPOSE_TIMINGS:
        raise HTTPException(status_code=404, detail="Not Found")

    timer, token = start_request_timer()
    response.headers["X-Request-ID"] = timer.request_id
    status = "error"

    try:
        with timed_stage("evidence_validation"):
            verdict = run_evidence_validation(
                question=request.question,
                answer=request.answer,
                sources=[source.model_dump() for source in request.sources],
                model=request.model,
                reasoning_effort=request.reasoning_effort,
                structured_output=request.structured_output,
            )

        status = "ok"

        return {
            "verdict": verdict,
            "error": None,
            "timings_ms": timer.summary(),
            "token_usage": timer.token_usage,
        }

    except Exception as exc:
        # Report the failure type so unsupported settings are visible.
        return {
            "verdict": None,
            "error": f"{type(exc).__name__}: {str(exc)[:300]}",
            "timings_ms": timer.summary(),
            "token_usage": timer.token_usage,
        }

    finally:
        timer.log_summary(status)
        end_request_timer(token)
