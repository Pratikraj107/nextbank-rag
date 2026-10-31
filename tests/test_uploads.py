"""
Upload and ingestion: validation, job states, indexing, retrieval of the new
document, duplicates, retries and failure handling.

Every test works on a temporary copy of data/processed, so the real files
are never modified. Jobs run synchronously so their states are deterministic.
The real embedding model is used; LLM calls are faked.
"""

import json
import re
import shutil
import zipfile
from concurrent.futures import Executor, Future
from io import BytesIO

import pytest
from docx import Document as DocxDocument
from fastapi.testclient import TestClient

import src.agents.rag_agent as rag_agent
import src.api.main as api
from src.api.documents import get_document_library
from src.api.uploads import get_ingestion_service
from src.documents.library import DocumentLibrary
from src.embeddings import semantic_search
from src.ingestion.processed_store import PROCESSED_DIR, ProcessedStore
from src.ingestion.uploads import (
    IngestionService,
    JobRegistry,
    ProcessingError,
    UploadRejected,
    safe_filename,
)
from src.retrieval import exact_search

BONUS_TEXT = [
    "Bonus Letter — Synthetic",
    "Employee: Lotte van Dijk",
    "Employer: Canal Analytics B.V.",
    "Annual performance bonus: EUR 3,750",
    "Bonus payment month: December 2026",
]


def docx_bytes(paragraphs: list[str]) -> bytes:
    document = DocxDocument()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def html_bytes(body: str) -> bytes:
    return f"<!doctype html><html><body>{body}</body></html>".encode()


EML_BYTES = (
    b"From: applicant-3001@example.invalid\r\nTo: lending@nexabank.example\r\n"
    b"Subject: Updated address\r\nDate: Mon, 05 Oct 2026 09:00:00 +0200\r\n"
    b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
    b"Beste NexaBank,\r\nMijn nieuwe adres is Prinsengracht 1, Amsterdam.\r\nLotte van Dijk\r\n"
)


class ImmediateExecutor(Executor):
    """Runs jobs on submit, so tests see final states without waiting."""

    def submit(self, fn, /, *args, **kwargs):
        future = Future()
        future.set_result(fn(*args, **kwargs))
        return future


@pytest.fixture
def processed(tmp_path, monkeypatch):
    """A private copy of data/processed wired into every reader."""
    directory = tmp_path / "processed"
    directory.mkdir()
    for name in ("documents.jsonl", "chunks.jsonl", "chunk_embeddings.jsonl"):
        shutil.copy(PROCESSED_DIR / name, directory / name)

    monkeypatch.setattr(semantic_search, "INPUT_FILE", str(directory / "chunk_embeddings.jsonl"))
    monkeypatch.setattr(semantic_search, "_store", None)
    monkeypatch.setattr(exact_search, "DOCUMENTS_PATH", directory / "documents.jsonl")
    return directory


@pytest.fixture
def service(processed, tmp_path):
    store = ProcessedStore(
        processed / "documents.jsonl", processed / "chunks.jsonl", processed / "chunk_embeddings.jsonl"
    )
    library = DocumentLibrary(store.documents_path, store.chunks_path)
    return IngestionService(
        upload_dir=tmp_path / "uploads", store=store, library=library,
        max_upload_bytes=200_000, executor=ImmediateExecutor(),
    )


@pytest.fixture
def client(service):
    api.app.dependency_overrides[get_ingestion_service] = lambda: service
    api.app.dependency_overrides[get_document_library] = lambda: service.library
    yield TestClient(api.app)
    api.app.dependency_overrides.clear()


def upload(client, data, filename="bonus_letter.docx", customer="NB-CUST-3001", loan="NB-LOAN-2101"):
    form = {"customer_id": customer}
    if loan:
        form["loan_id"] = loan
    return client.post("/api/documents/upload", files={"file": (filename, data)}, data=form)


def records_for(path, source):
    return [r for r in map(json.loads, path.read_text().splitlines()) if r.get("source") == source]

# ------------------------------------------------------------
# Successful upload and indexing
# ------------------------------------------------------------

def test_successful_upload_is_ready_and_indexed(client, service, processed):
    response = upload(client, docx_bytes(BONUS_TEXT))

    assert response.status_code == 202
    body = response.json()
    job = body["job"]
    assert body["duplicate"] is False
    assert job["status"] == "ready" and job["step"] == "done"
    assert job["chunk_count"] >= 1
    assert job["customer_id"] == "NB-CUST-3001" and job["loan_id"] == "NB-LOAN-2101"
    assert re.fullmatch(r"doc_[0-9a-f]{16}", job["document_id"])
    assert "source" not in job and "/" not in job["filename"]  # no filesystem paths

    source = service.jobs.get(job["job_id"]).source
    [document] = records_for(processed / "documents.jsonl", source)
    chunks = records_for(processed / "chunks.jsonl", source)
    embeddings = records_for(processed / "chunk_embeddings.jsonl", source)

    assert "Annual performance bonus: EUR 3,750" in document["content"]
    assert document["customer_id"] == "NB-CUST-3001" and document["loan_id"] == "NB-LOAN-2101"
    assert len(chunks) == len(embeddings) == job["chunk_count"]
    assert all(len(e["embedding"]) == 768 for e in embeddings)
    assert {c["chunk_id"] for c in chunks} == {e["chunk_id"] for e in embeddings}


def test_job_passes_through_every_state_in_order(service):
    seen = []
    original = service.jobs.save
    service.jobs.save = lambda job: (seen.append((job.status, job.step)), original(job))

    job, _ = service.submit(docx_bytes(BONUS_TEXT), "bonus.docx", "NB-CUST-3001", None)

    # Each stage is saved when it starts and again when it completes.
    assert seen == [
        ("uploaded", "queued"),
        *[("processing", stage) for stage in
          ("parsing", "normalization", "chunking", "embedding", "indexing") for _ in (0, 1)],
        ("ready", "done"),
    ]
    assert service.jobs.get(job.job_id).finished_at is not None


def test_job_status_endpoint(client):
    job = upload(client, docx_bytes(BONUS_TEXT)).json()["job"]

    status = client.get(f"/api/jobs/{job['job_id']}").json()
    assert status["status"] == "ready" and status["step_index"] == status["step_count"]
    assert client.get("/api/jobs/" + "0" * 32).status_code == 404
    assert client.get("/api/jobs/../../etc/passwd").status_code == 404


@pytest.mark.parametrize(
    "data, filename",
    [(lambda: html_bytes("<h1>Note</h1><p>Lotte van Dijk prefers email contact.</p>"), "note.html"),
     (lambda: EML_BYTES, "update.eml")],
)
def test_html_and_eml_uploads(client, data, filename):
    job = upload(client, data(), filename=filename, loan=None).json()["job"]

    assert job["status"] == "ready"
    assert job["loan_id"] is None

# ------------------------------------------------------------
# New document is visible to every reader
# ------------------------------------------------------------

def test_document_appears_in_explorer_with_chunks(client):
    job = upload(client, docx_bytes(BONUS_TEXT)).json()["job"]

    listing = client.get("/api/documents", params={"q": "bonus_letter"}).json()
    assert [item["id"] for item in listing["items"]] == [job["document_id"]]

    detail = client.get(f"/api/documents/{job['document_id']}").json()
    assert detail["customer_id"] == "NB-CUST-3001"
    assert detail["metadata"]["upload"]["job_id"] == job["job_id"]

    chunks = client.get(f"/api/documents/{job['document_id']}/chunks").json()
    assert chunks["total"] == job["chunk_count"]
    assert any("3,750" in chunk["content"] for chunk in chunks["chunks"])


def test_exact_search_finds_new_content(service):
    service.submit(docx_bytes(BONUS_TEXT), "bonus_letter.docx", "NB-CUST-3001", "NB-LOAN-2101")

    result = exact_search.exact_search("Annual performance bonus")

    assert result["documents_matched"] == 1
    assert result["results"][0]["source"].endswith("bonus_letter.docx")


def test_semantic_search_finds_new_chunks(service):
    job, _ = service.submit(docx_bytes(BONUS_TEXT), "bonus_letter.docx", "NB-CUST-3001", "NB-LOAN-2101")

    results = semantic_search.search(
        "What is Lotte van Dijk's annual performance bonus?", top_k=3, customer_id="NB-CUST-3001"
    )

    assert results[0]["chunk"]["source"] == job.source


def test_agent_answers_from_uploaded_document_with_valid_citation(service, fake_llm):
    job, _ = service.submit(docx_bytes(BONUS_TEXT), "bonus_letter.docx", "NB-CUST-3001", "NB-LOAN-2101")

    def generator(prompt: str) -> str:
        # Cite whichever evidence block the real retrieval labelled for the upload.
        blocks = re.split(r"\n(?=\[S\d+\]\n)", prompt)
        label = next(re.match(r"\[(S\d+)\]", b).group(1) for b in blocks
                     if re.match(r"\[S\d+\]", b) and "3,750" in b)
        return f"Lotte van Dijk's annual performance bonus is EUR 3,750 [{label}]."

    fake_llm.generator = generator

    result = rag_agent.ask_agent("What is Lotte van Dijk's annual performance bonus?")

    assert result["semantic_valid"] is True and result["is_valid"] is True
    label = re.search(r"\[(S\d+)\]", result["answer"]).group(1)
    cited = next(s for s in result["sources"] if s["source_id"] == label)
    assert cited["source"] == job.source
    assert "3,750" in cited["content"]

# ------------------------------------------------------------
# Rejected uploads
# ------------------------------------------------------------

@pytest.mark.parametrize(
    "data, filename, status, message",
    [
        (b"plain text", "notes.txt", 415, "Unsupported file type '.txt'"),
        (b"a,b\n1,2\n", "export.csv", 415, "Unsupported file type '.csv'"),
        (b"", "empty.docx", 400, "The file is empty"),
        (b"x" * 200_001, "big.pdf", 413, "larger than"),
        (b"not a pdf at all", "fake.pdf", 415, "does not look like a PDF"),
        (b"PK\x03\x04garbage", "broken.docx", 415, "Word (.docx)"),
        (html_bytes("x").replace(b"<!doctype html><html><body>", b"")[:-14], "x.html", 415, "HTML"),
        (b"\x00\x01binary", "x.html", 415, "binary data"),
        (b"just some text", "x.eml", 415, "email"),
    ],
)
def test_invalid_files_are_rejected(client, service, data, filename, status, message):
    response = upload(client, data, filename=filename)

    assert response.status_code == status
    assert message in response.json()["detail"]
    assert not list(service.upload_dir.glob("*"))  # nothing stored


def test_docx_extension_on_zip_without_word_content_is_rejected(client):
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", "hello")

    assert upload(client, buffer.getvalue(), filename="x.docx").status_code == 415


@pytest.mark.parametrize(
    "customer, loan, message",
    [
        ("NB-CUST-9999", None, "not in the enterprise customer records"),
        ("lotte", None, "must look like NB-CUST-3001"),
        ("NB-CUST-3001", "NB-LOAN-2102", "belongs to NB-CUST-3002, not NB-CUST-3001"),
        ("NB-CUST-3001", "NB-LOAN-9999", "not in the enterprise loan records"),
    ],
)
def test_customer_and_loan_are_validated(client, customer, loan, message):
    response = upload(client, docx_bytes(BONUS_TEXT), customer=customer, loan=loan)

    assert response.status_code == 422
    assert message in response.json()["detail"]


def test_unsafe_filenames_are_sanitised(service):
    job, _ = service.submit(docx_bytes(BONUS_TEXT), "../../etc/pass wd?.DOCX", "NB-CUST-3001", None)

    assert job.filename == "pass_wd.docx"
    stored = list(service.upload_dir.rglob("*.docx"))
    assert [path.parent.parent for path in stored] == [service.upload_dir]
    assert safe_filename("..\\..\\x.pdf") == "x.pdf"
    assert safe_filename("....pdf") == "document.pdf"

# ------------------------------------------------------------
# Failures never produce a ready document
# ------------------------------------------------------------

def test_parser_failure_marks_job_failed_and_writes_nothing(service, processed):
    before = (processed / "documents.jsonl").read_text()

    job, _ = service.submit(b"%PDF-1.4\nthis is not really a pdf", "broken.pdf", "NB-CUST-3001", None)

    assert job.status == "failed" and job.step == "parsing"
    assert "could not be read as PDF" in job.error
    assert (processed / "documents.jsonl").read_text() == before
    assert service.library.get(job.document_id) is None


def test_identifier_conflict_inside_document_fails_ingestion(service, processed):
    note = html_bytes(
        "<p>Credit Analyst Notes</p><p>Loan reference: NB-LOAN-2102</p>"
        "<p>Customer: NB-CUST-3002</p><p>Documents expected: payslip</p>"
        "<p>Status: DOCUMENT REVIEW PENDING</p>"
    )

    job, _ = service.submit(note, "analyst_note.html", "NB-CUST-3001", "NB-LOAN-2101")

    assert job.status == "failed"
    assert "uploaded for" in job.error
    assert not records_for(processed / "documents.jsonl", job.source)


def test_failure_after_indexing_rolls_back(service, processed, monkeypatch):
    def broken_verify(job, chunks):
        raise ProcessingError("The document did not appear in semantic search.")

    monkeypatch.setattr(service, "_verify", broken_verify)

    job, _ = service.submit(docx_bytes(BONUS_TEXT), "bonus.docx", "NB-CUST-3001", None)

    assert job.status == "failed" and job.step == "indexing"
    for name in ("documents.jsonl", "chunks.jsonl", "chunk_embeddings.jsonl"):
        assert not records_for(processed / name, job.source)
    assert service.library.get(job.document_id) is None


def test_unexpected_errors_are_reported_without_internal_details(service, monkeypatch):
    def explode(document):
        raise RuntimeError("secret internal detail /Users/x")

    monkeypatch.setattr(service, "_chunk", explode)

    job, _ = service.submit(docx_bytes(BONUS_TEXT), "bonus.docx", "NB-CUST-3001", None)

    assert job.status == "failed"
    assert job.error == "Processing failed unexpectedly (RuntimeError)."

# ------------------------------------------------------------
# Duplicates, retries and restarts
# ------------------------------------------------------------

def test_duplicate_upload_returns_existing_job(client, service, processed):
    first = upload(client, docx_bytes(BONUS_TEXT)).json()
    second = upload(client, docx_bytes(BONUS_TEXT)).json()

    assert second["duplicate"] is True
    assert second["job"]["job_id"] == first["job"]["job_id"]
    source = service.jobs.get(first["job"]["job_id"]).source
    assert len(records_for(processed / "documents.jsonl", source)) == 1
    assert len(list(service.upload_dir.glob("*/job.json"))) == 1


def test_same_file_for_another_loan_is_a_new_job(client):
    first = upload(client, docx_bytes(BONUS_TEXT), loan="NB-LOAN-2101").json()
    second = upload(client, docx_bytes(BONUS_TEXT), loan=None).json()

    assert second["duplicate"] is False
    assert second["job"]["job_id"] != first["job"]["job_id"]


def test_retry_after_failure_succeeds_without_duplicates(client, service, processed, monkeypatch):
    calls = {"n": 0}
    real_embed = service._embed

    def flaky_embed(chunks):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ProcessingError("Embedding service unavailable.")
        return real_embed(chunks)

    monkeypatch.setattr(service, "_embed", flaky_embed)

    job = upload(client, docx_bytes(BONUS_TEXT)).json()["job"]
    assert job["status"] == "failed"

    retried = client.post(f"/api/jobs/{job['job_id']}/retry").json()
    assert retried["status"] == "ready" and retried["attempts"] == 2

    source = service.jobs.get(job["job_id"]).source
    assert len(records_for(processed / "documents.jsonl", source)) == 1
    assert len(records_for(processed / "chunks.jsonl", source)) == retried["chunk_count"]


def test_reprocessing_a_ready_document_does_not_duplicate_records(service, processed):
    job, _ = service.submit(docx_bytes(BONUS_TEXT), "bonus.docx", "NB-CUST-3001", None)
    service._run(job.job_id)

    assert len(records_for(processed / "documents.jsonl", job.source)) == 1
    assert len(records_for(processed / "chunks.jsonl", job.source)) == job.chunk_count


def test_only_failed_jobs_can_be_retried(client):
    job = upload(client, docx_bytes(BONUS_TEXT)).json()["job"]

    response = client.post(f"/api/jobs/{job['job_id']}/retry")

    assert response.status_code == 409


def test_restart_marks_interrupted_jobs_failed(service):
    job, _ = service.submit(docx_bytes(BONUS_TEXT), "bonus.docx", "NB-CUST-3001", None)
    job.status, job.step = "processing", "embedding"
    service.jobs.save(job)

    reloaded = JobRegistry(service.upload_dir).get(job.job_id)

    assert reloaded.status == "failed"
    assert "server restart" in reloaded.error


def test_upload_options(client):
    options = client.get("/api/documents/upload-options").json()

    assert options["allowed_extensions"] == [".docx", ".eml", ".htm", ".html", ".pdf"]
    assert options["max_upload_bytes"] == 200_000
    assert "NB-CUST-3001" in options["customers"]
    assert {"loan_id": "NB-LOAN-2101", "customer_id": "NB-CUST-3001"} in options["loans"]


def test_upload_rejected_carries_status():
    assert UploadRejected("x", 413).status_code == 413
