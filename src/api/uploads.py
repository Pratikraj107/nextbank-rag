"""
Document upload and ingestion-job endpoints.

    GET  /api/documents/upload-options   accepted formats, size limit, customers, loans
    POST /api/documents/upload           multipart: file, customer_id, loan_id (optional)
    GET  /api/jobs                       job list (filters: status, customer_id, document_type)
    GET  /api/jobs/{job_id}              ingestion status with per-stage detail
    POST /api/jobs/{job_id}/retry        re-run a failed job

Local prototype: no authentication; see src/ingestion/uploads.py for
storage and restart behaviour.
"""

import math
import threading
from collections import Counter
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel

from src.api.documents import get_document_library
from src.ingestion.uploads import IngestionService, UploadRejected

router = APIRouter(tags=["uploads"])

_service: IngestionService | None = None
_service_lock = threading.Lock()


def get_ingestion_service() -> IngestionService:
    """Created on first use; tests override this dependency."""
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = IngestionService(library=get_document_library())
    return _service


class LoanOption(BaseModel):
    loan_id: str
    customer_id: str


class UploadOptions(BaseModel):
    allowed_extensions: list[str]
    max_upload_bytes: int
    customers: list[str]
    loans: list[LoanOption]


class StageResponse(BaseModel):
    name: str
    status: Literal["pending", "running", "completed", "failed"]
    started_at: str | None
    finished_at: str | None
    duration_ms: float | None
    error: str | None


class JobResponse(BaseModel):
    job_id: str
    document_id: str
    filename: str
    extension: str
    size_bytes: int
    checksum: str
    customer_id: str
    loan_id: str | None
    status: str
    step: str
    step_index: int
    step_count: int
    created_at: str
    updated_at: str
    started_at: str | None
    finished_at: str | None
    attempts: int
    error: str | None
    warnings: list[str]
    document_type: str | None
    chunk_count: int | None
    stages: list[StageResponse]
    failed_stage: str | None
    retryable: bool
    # Latest attempt, from queued to completion (or until now while running).
    duration_ms: float | None
    queued_at: str | None


class FacetValue(BaseModel):
    value: str
    count: int


class JobFacets(BaseModel):
    statuses: list[FacetValue]
    customer_ids: list[FacetValue]
    document_types: list[FacetValue]


class JobListResponse(BaseModel):
    items: list[JobResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
    # Filter values across all jobs, not just this page.
    facets: JobFacets


class UploadResponse(BaseModel):
    job: JobResponse
    # True when this exact file was already uploaded for the same customer and loan.
    duplicate: bool


def _read_limited(upload: UploadFile, limit: int) -> bytes:
    """Read at most limit + 1 bytes so oversized uploads are rejected without buffering them."""
    data = bytearray()
    while len(data) <= limit:
        block = upload.file.read(min(1024 * 1024, limit + 1 - len(data)))
        if not block:
            break
        data.extend(block)
    return bytes(data)


@router.get("/api/documents/upload-options", response_model=UploadOptions)
def upload_options(service: IngestionService = Depends(get_ingestion_service)):
    return service.options()


@router.post(
    "/api/documents/upload",
    response_model=UploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def upload_document(
    file: UploadFile = File(...),
    customer_id: str = Form(..., max_length=40),
    loan_id: str | None = Form(default=None, max_length=40),
    service: IngestionService = Depends(get_ingestion_service),
):
    data = _read_limited(file, service.max_upload_bytes)

    try:
        job, duplicate = service.submit(data, file.filename or "", customer_id, loan_id)
    except UploadRejected as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    return UploadResponse(job=JobResponse(**job.public()), duplicate=duplicate)


def _facets(values) -> list[FacetValue]:
    return [FacetValue(value=v, count=c) for v, c in sorted(Counter(v for v in values if v).items())]


@router.get("/api/jobs", response_model=JobListResponse)
def list_jobs(
    status_filter: Literal["uploaded", "processing", "ready", "failed"] | None = Query(default=None, alias="status"),
    customer_id: str | None = Query(default=None, max_length=40),
    document_type: str | None = Query(default=None, max_length=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    service: IngestionService = Depends(get_ingestion_service),
):
    matching = service.list_jobs(status=status_filter, customer_id=customer_id, document_type=document_type)
    every_job = service.jobs.all()
    start = (page - 1) * page_size

    return JobListResponse(
        items=[JobResponse(**job.public()) for job in matching[start:start + page_size]],
        total=len(matching),
        page=page,
        page_size=page_size,
        total_pages=max(1, math.ceil(len(matching) / page_size)),
        facets=JobFacets(
            statuses=_facets(job.status for job in every_job),
            customer_ids=_facets(job.customer_id for job in every_job),
            document_types=_facets(job.document_type for job in every_job),
        ),
    )


@router.get("/api/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: str, service: IngestionService = Depends(get_ingestion_service)):
    service.reconcile()
    job = service.jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return JobResponse(**job.public())


@router.post("/api/jobs/{job_id}/retry", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
def retry_job(job_id: str, service: IngestionService = Depends(get_ingestion_service)):
    try:
        job = service.retry(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Job not found.") from exc
    except UploadRejected as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return JobResponse(**job.public())
