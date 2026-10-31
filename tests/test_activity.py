"""
Activity Center: per-stage job tracking, failures at each stage, retry
eligibility, consistency with the index, the job list API, and isolation
of existing documents. Uses the fixtures from test_uploads (a private copy
of data/processed and synchronous jobs).
"""

import json

import numpy as np
import pytest

from src.documents.library import DocumentLibrary
from src.embeddings import semantic_search
from src.ingestion.uploads import STAGES, JobRegistry, ProcessingError
from src.ingestion.uploads import _elapsed_ms as _elapsed
from tests.test_uploads import (  # noqa: F401  (fixtures)
    BONUS_TEXT,
    client,
    docx_bytes,
    processed,
    records_for,
    service,
    upload,
)

STAGE_NAMES = list(STAGES)


def stages(job) -> dict[str, dict]:
    return {stage["name"]: stage for stage in job.stages}


def assert_nothing_indexed(processed_dir, source):
    for name in ("documents.jsonl", "chunks.jsonl", "chunk_embeddings.jsonl"):
        assert not records_for(processed_dir / name, source), name

# ------------------------------------------------------------
# Successful processing records every stage
# ------------------------------------------------------------

def test_every_stage_completes_with_timestamps(service):
    job, _ = service.submit(docx_bytes(BONUS_TEXT), "bonus.docx", "NB-CUST-3001", None)

    assert job.status == "ready" and job.failed_stage is None and job.error is None
    assert [stage["name"] for stage in job.stages] == STAGE_NAMES
    for stage in job.stages:
        assert stage["status"] == "completed", stage["name"]
        assert stage["started_at"] and stage["finished_at"], stage["name"]
        assert stage["duration_ms"] >= 0 and stage["error"] is None

    public = job.public()
    assert public["duration_ms"] >= 0 and "source" not in public


def test_stage_status_transitions_are_ordered(service):
    snapshots = []
    original = service.jobs.save

    def record(job):
        snapshots.append({s["name"]: s["status"] for s in job.stages})
        original(job)

    service.jobs.save = record
    service.submit(docx_bytes(BONUS_TEXT), "bonus.docx", "NB-CUST-3001", None)

    # Each background stage goes pending -> running -> completed, one at a time.
    for name in STAGE_NAMES[1:]:
        history = [snapshot[name] for snapshot in snapshots]
        assert history.index("running") < history.index("completed")
        assert "pending" not in history[history.index("running"):]
    assert all(sum(v == "running" for v in s.values()) <= 1 for s in snapshots)

# ------------------------------------------------------------
# Failures at each stage
# ------------------------------------------------------------

def test_parsing_failure_is_recorded_and_not_retryable(client, service, processed):
    body = upload(client, b"%PDF-1.4\nnot really a pdf", filename="broken.pdf", loan=None).json()
    job = service.jobs.get(body["job"]["job_id"])

    assert job.status == "failed" and job.failed_stage == "parsing"
    assert stages(job)["parsing"]["status"] == "failed"
    assert "could not be read as PDF" in stages(job)["parsing"]["error"]
    assert all(stages(job)[name]["status"] == "pending" for name in STAGE_NAMES[2:])
    assert job.retryable is False
    assert_nothing_indexed(processed, job.source)

    response = client.post(f"/api/jobs/{job.job_id}/retry")
    assert response.status_code == 409 and "cannot be retried" in response.json()["detail"]


@pytest.mark.parametrize(
    "error, message",
    [
        (ProcessingError("Embedding service unavailable."), "Embedding service unavailable."),
        (RuntimeError("internal detail"), "Processing failed unexpectedly (RuntimeError)."),
    ],
)
def test_embedding_failure_is_recorded_and_retryable(service, processed, monkeypatch, error, message):
    def broken_embed(chunks):
        raise error

    monkeypatch.setattr(service, "_embed", broken_embed)

    job, _ = service.submit(docx_bytes(BONUS_TEXT), "bonus.docx", "NB-CUST-3001", None)

    assert job.status == "failed" and job.failed_stage == "embedding"
    assert job.error == message and stages(job)["embedding"]["error"] == message
    assert [stages(job)[n]["status"] for n in ("parsing", "normalization", "chunking")] == ["completed"] * 3
    assert stages(job)["indexing"]["status"] == "pending"
    assert job.retryable is True
    assert_nothing_indexed(processed, job.source)


def test_indexing_failure_mid_write_leaves_nothing_searchable(service, processed, monkeypatch):
    """The documents file is written, then the chunks write fails: everything is rolled back."""
    real_append = service.store._append
    calls = {"chunks": 0}

    def failing_append(path, records):
        if path == service.store.chunks_path and calls["chunks"] == 0:
            calls["chunks"] += 1
            raise OSError("disk full")
        return real_append(path, records)

    monkeypatch.setattr(service.store, "_append", failing_append)

    job, _ = service.submit(docx_bytes(BONUS_TEXT), "bonus.docx", "NB-CUST-3001", None)

    assert job.status == "failed" and job.failed_stage == "indexing"
    assert job.retryable is True
    assert_nothing_indexed(processed, job.source)
    assert service.library.get(job.document_id) is None
    store = semantic_search.get_chunk_store()
    assert not any(chunk["source"] == job.source for chunk in store.chunks)

    # Retrying succeeds and writes exactly one copy of everything.
    retried = service.retry(job.job_id)
    assert retried.status == "ready" and retried.attempts == 2
    assert len(records_for(processed / "documents.jsonl", job.source)) == 1
    chunks = records_for(processed / "chunks.jsonl", job.source)
    embeddings = records_for(processed / "chunk_embeddings.jsonl", job.source)
    assert len(chunks) == len(embeddings) == retried.chunk_count
    assert len({c["chunk_id"] for c in chunks}) == len(chunks)


def test_retry_resets_stages_but_keeps_upload_validation(service, monkeypatch):
    calls = {"n": 0}
    real_chunk = service._chunk

    def flaky_chunk(document):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient")
        return real_chunk(document)

    monkeypatch.setattr(service, "_chunk", flaky_chunk)
    job, _ = service.submit(docx_bytes(BONUS_TEXT), "bonus.docx", "NB-CUST-3001", None)
    validation_before = dict(stages(job)["validation"])

    job = service.retry(job.job_id)

    assert job.status == "ready" and job.error is None and job.failed_stage is None
    assert stages(job)["validation"] == validation_before
    # Duration covers the retry attempt only, not the time since the original upload.
    assert job.queued_at > job.created_at
    assert job.public()["duration_ms"] <= _elapsed(job.created_at, job.finished_at)
    assert all(stage["status"] == "completed" for stage in job.stages)

# ------------------------------------------------------------
# Duplicates
# ------------------------------------------------------------

def test_duplicate_of_permanently_failed_job_is_not_reprocessed(service):
    data = b"%PDF-1.4\nnot really a pdf"
    first, _ = service.submit(data, "broken.pdf", "NB-CUST-3001", None)
    second, duplicate = service.submit(data, "broken.pdf", "NB-CUST-3001", None)

    assert duplicate is True and second.job_id == first.job_id
    assert second.status == "failed" and second.attempts == 1


def test_duplicate_of_retryable_failure_is_retried(service, monkeypatch):
    calls = {"n": 0}
    real_embed = service._embed

    def flaky_embed(chunks):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ProcessingError("Embedding service unavailable.")
        return real_embed(chunks)

    monkeypatch.setattr(service, "_embed", flaky_embed)
    first, _ = service.submit(docx_bytes(BONUS_TEXT), "bonus.docx", "NB-CUST-3001", None)
    second, duplicate = service.submit(docx_bytes(BONUS_TEXT), "bonus.docx", "NB-CUST-3001", None)

    assert duplicate is True and second.job_id == first.job_id
    assert second.status == "ready" and second.attempts == 2

# ------------------------------------------------------------
# Job state stays consistent with the index
# ------------------------------------------------------------

def test_ready_job_whose_document_left_the_index_is_flagged(client, service):
    job, _ = service.submit(docx_bytes(BONUS_TEXT), "bonus.docx", "NB-CUST-3001", None)
    service.store.remove_source(job.source)  # e.g. a batch rebuild of data/processed

    body = client.get(f"/api/jobs/{job.job_id}").json()

    assert body["status"] == "failed" and body["failed_stage"] == "indexing"
    assert body["retryable"] is True and "no longer in the search index" in body["error"]

    assert client.post(f"/api/jobs/{job.job_id}/retry").json()["status"] == "ready"
    assert service.library.get(job.document_id) is not None


def test_restart_marks_running_stage_failed(service):
    job, _ = service.submit(docx_bytes(BONUS_TEXT), "bonus.docx", "NB-CUST-3001", None)
    job.status, job.step = "processing", "embedding"
    stages(job)["embedding"].update(status="running")
    service.jobs.save(job)

    reloaded = JobRegistry(service.upload_dir).get(job.job_id)

    assert reloaded.status == "failed" and reloaded.failed_stage == "embedding"
    assert stages(reloaded)["embedding"]["status"] == "failed" and reloaded.retryable is True


@pytest.mark.parametrize("status, step", [("ready", "done"), ("failed", "verifying")])
def test_jobs_recorded_before_stage_tracking_are_migrated(service, status, step):
    job, _ = service.submit(docx_bytes(BONUS_TEXT), "bonus.docx", "NB-CUST-3001", None)
    path = service.upload_dir / job.job_id / "job.json"
    legacy = json.loads(path.read_text())
    for key in ("stages", "failed_stage", "retryable"):
        legacy.pop(key)
    legacy.update(status=status, step=step, error="old error" if status == "failed" else None)
    path.write_text(json.dumps(legacy))

    migrated = JobRegistry(service.upload_dir).get(job.job_id)

    assert [s["name"] for s in migrated.stages] == STAGE_NAMES
    if status == "ready":
        assert all(s["status"] == "completed" for s in migrated.stages)
    else:
        assert migrated.failed_stage == "indexing" and migrated.retryable is True
        assert stages(migrated)["indexing"]["status"] == "failed"
    assert "stages" in json.loads(path.read_text())  # migration is saved

# ------------------------------------------------------------
# Job list API
# ------------------------------------------------------------

def test_job_list_filters_sorting_and_facets(client, service):
    ready = upload(client, docx_bytes(BONUS_TEXT), loan=None).json()["job"]
    failed = upload(client, b"%PDF-1.4\nbroken", filename="broken.pdf", customer="NB-CUST-3002", loan=None).json()["job"]

    body = client.get("/api/jobs").json()
    assert body["total"] == 2
    assert [item["job_id"] for item in body["items"]] == [failed["job_id"], ready["job_id"]]  # newest first
    assert {f["value"]: f["count"] for f in body["facets"]["statuses"]} == {"failed": 1, "ready": 1}
    assert {f["value"] for f in body["facets"]["customer_ids"]} == {"NB-CUST-3001", "NB-CUST-3002"}

    assert [i["job_id"] for i in client.get("/api/jobs", params={"status": "failed"}).json()["items"]] == [failed["job_id"]]
    assert client.get("/api/jobs", params={"customer_id": "NB-CUST-3001"}).json()["total"] == 1
    assert client.get("/api/jobs", params={"document_type": "unknown"}).json()["total"] == 1
    assert client.get("/api/jobs", params={"page_size": 1, "page": 2}).json()["items"][0]["job_id"] == ready["job_id"]
    assert client.get("/api/jobs", params={"status": "bogus"}).status_code == 422

    item = body["items"][1]
    assert [s["name"] for s in item["stages"]] == STAGE_NAMES
    assert item["duration_ms"] >= 0 and "source" not in item


def test_empty_job_list(client):
    body = client.get("/api/jobs").json()

    assert body["items"] == [] and body["total"] == 0 and body["total_pages"] == 1

# ------------------------------------------------------------
# Model loading and existing documents
# ------------------------------------------------------------

class CountingModel:
    instances = 0

    def __init__(self, name):
        CountingModel.instances += 1

    def encode(self, texts):
        return np.full((len(texts), 768), 0.1)


def test_embedding_model_is_loaded_once_across_uploads(service, monkeypatch):
    CountingModel.instances = 0
    monkeypatch.setattr(semantic_search, "SentenceTransformer", CountingModel)
    monkeypatch.setattr(semantic_search, "_model", None)

    service.submit(docx_bytes(BONUS_TEXT), "a.docx", "NB-CUST-3001", None)
    service.submit(docx_bytes(BONUS_TEXT + ["Second letter"]), "b.docx", "NB-CUST-3002", None)

    assert CountingModel.instances == 1


def test_existing_documents_and_retrieval_are_unaffected(service, processed):
    before = {d.id: len(d.chunks) for d in DocumentLibrary(service.store.documents_path, service.store.chunks_path).all()}

    service.submit(docx_bytes(BONUS_TEXT), "bonus.docx", "NB-CUST-3001", None)
    service.submit(b"%PDF-1.4\nbroken", "broken.pdf", "NB-CUST-3001", None)

    after = {d.id: len(d.chunks) for d in DocumentLibrary(service.store.documents_path, service.store.chunks_path).all()}
    assert {k: v for k, v in after.items() if k in before} == before
    assert len(after) == len(before) + 1

    results = semantic_search.search(
        "What is Thomas de Boer's monthly gross salary?", top_k=2,
        customer_id="NB-CUST-3002", document_type="payslip",
    )
    assert results[0]["chunk"]["source"] == "data/raw/NB-LOAN-2102/pdf/03_payslip.pdf"
