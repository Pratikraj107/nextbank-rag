"""
Upload and ingest a single document through the existing pipeline.

Flow for one upload (a "job"):

    submit   validate request, check content type, store the original file,
             record the job                                   -> uploaded
    worker   parse with IngestionPipeline (existing parsers,
             classifier, metadata extractor, validator)       -> processing
             check customer/loan identifiers
             chunk with the existing RecursiveChunker
             embed the new chunks with the loaded model
             write all records with ProcessedStore
             confirm every reader can see the document        -> ready
             any failure rolls back written records           -> failed

Storage (local prototype):
    <upload dir>/<job_id>/<sanitised filename>   original bytes
    <upload dir>/<job_id>/job.json               job record

Jobs run one at a time on a single background thread inside the API
process. The queue is in memory: if the API restarts mid-job, that job is
marked failed on the next start and can be retried. Job records and
original files persist on disk.
"""

import email.parser
import hashlib
import json
import logging
import os
import re
import tempfile
import threading
import time
import unicodedata
import uuid
import zipfile
from concurrent.futures import Executor, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from src.chunking.recursive import RecursiveChunker
from src.documents.library import DocumentLibrary, normalize_source, stable_document_id
from src.ingestion.processed_store import PROJECT_ROOT, ProcessedStore
from src.models.chunk import DocumentChunk
from src.retrieval.query_analyzer import load_verified_entities

logger = logging.getLogger("nexabank.ingestion")

UPLOAD_DIR = Path(os.getenv("NEXABANK_UPLOAD_DIR", str(PROJECT_ROOT / "data" / "uploads")))
MAX_UPLOAD_BYTES = int(float(os.getenv("NEXABANK_MAX_UPLOAD_MB", "10")) * 1024 * 1024)

# CSV is deliberately excluded: the existing CSV inputs are system exports
# holding many customers' rows, not a document belonging to one customer.
ALLOWED_EXTENSIONS = {".pdf": "pdf", ".docx": "docx", ".html": "html", ".htm": "html", ".eml": "eml"}

JOB_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
CUSTOMER_ID_PATTERN = re.compile(r"^NB-CUST-\d+$")
LOAN_ID_PATTERN = re.compile(r"^NB-LOAN-\d+$")

# Same settings as src/chunking/pipeline.py, so uploads chunk like the corpus.
CHUNK_SIZE = 200
CHUNK_OVERLAP = 50

STATUSES = ("uploaded", "processing", "ready", "failed")

# Processing stages, in order. "validation" runs during the upload request;
# the rest run in the background worker. "indexing" covers writing the
# records and confirming every reader can see them.
STAGES = ("validation", "parsing", "normalization", "chunking", "embedding", "indexing")

# The job's current position, kept for clients that read a single step.
STEPS = ("queued", *STAGES[1:], "done")


class UploadRejected(ValueError):
    """The request cannot be accepted. Carries an HTTP status code."""

    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


class ProcessingError(RuntimeError):
    """
    A processing failure whose message is safe to show to the user.

    `retryable` is False when running the job again cannot help, e.g. an
    unreadable file or identifiers that contradict the upload.
    """

    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


def _safe_message(exc: BaseException) -> str:
    """Show ProcessingError messages; hide details of unexpected errors."""
    if isinstance(exc, ProcessingError):
        return str(exc)
    return f"Processing failed unexpectedly ({type(exc).__name__})."


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _elapsed_ms(start: str | None, end: str | None) -> float | None:
    if not start or not end:
        return None
    delta = datetime.fromisoformat(end) - datetime.fromisoformat(start)
    return round(delta.total_seconds() * 1000, 1)


def new_stages() -> list[dict]:
    return [
        {"name": name, "status": "pending", "started_at": None, "finished_at": None,
         "duration_ms": None, "error": None}
        for name in STAGES
    ]


# ------------------------------------------------------------
# Request validation
# ------------------------------------------------------------

def safe_filename(original: str) -> str:
    """Reduce a client filename to a safe basename (no paths, no odd characters)."""
    name = re.split(r"[\\/]", original or "")[-1]
    name = unicodedata.normalize("NFKC", name)
    stem, dot, extension = name.rpartition(".")
    if not dot:
        stem, extension = name, ""
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-")[:80] or "document"
    extension = re.sub(r"[^A-Za-z0-9]", "", extension).lower()[:10]
    return f"{stem}.{extension}" if extension else stem


def check_content(kind: str, data: bytes) -> None:
    """Confirm the bytes really are the claimed format; the filename is not trusted."""
    if kind == "pdf":
        if not data.startswith(b"%PDF-"):
            raise UploadRejected("The file does not look like a PDF.", 415)
        return

    if kind == "docx":
        try:
            with zipfile.ZipFile(BytesIO(data)) as archive:
                names = set(archive.namelist())
        except zipfile.BadZipFile as exc:
            raise UploadRejected("The file does not look like a Word (.docx) document.", 415) from exc
        if "word/document.xml" not in names or "[Content_Types].xml" not in names:
            raise UploadRejected("The file does not look like a Word (.docx) document.", 415)
        return

    # HTML and EML are text formats.
    if b"\x00" in data:
        raise UploadRejected("The file contains binary data, not text.", 415)
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise UploadRejected("Text files must be UTF-8 encoded.", 415) from exc

    if kind == "html":
        head = text[:4096].lower()
        if not any(marker in head for marker in ("<!doctype html", "<html", "<body")):
            raise UploadRejected("The file does not look like an HTML document.", 415)
        return

    if kind == "eml":
        headers = email.parser.Parser().parsestr(text, headersonly=True)
        if not any(headers.get(name) for name in ("From", "To", "Subject", "Date")):
            raise UploadRejected("The file does not look like an email (.eml) message.", 415)
        return

    raise UploadRejected("Unsupported file type.", 415)


def validate_identifiers(customer_id: str, loan_id: str | None) -> tuple[str, str | None]:
    """Check the customer and loan against the verified enterprise records."""
    customer_id = (customer_id or "").strip().upper()
    loan_id = (loan_id or "").strip().upper() or None
    names_to_customers, loans_to_customers = load_verified_entities()
    known_customers = set(names_to_customers.values()) | set(loans_to_customers.values())

    if not CUSTOMER_ID_PATTERN.fullmatch(customer_id):
        raise UploadRejected("Customer ID must look like NB-CUST-3001.")
    if customer_id not in known_customers:
        raise UploadRejected(f"Customer {customer_id} is not in the enterprise customer records.")

    if loan_id is not None:
        if not LOAN_ID_PATTERN.fullmatch(loan_id):
            raise UploadRejected("Loan ID must look like NB-LOAN-2101.")
        owner = loans_to_customers.get(loan_id)
        if owner is None:
            raise UploadRejected(f"Loan {loan_id} is not in the enterprise loan records.")
        if owner != customer_id:
            raise UploadRejected(f"Loan {loan_id} belongs to {owner}, not {customer_id}.")

    return customer_id, loan_id


# ------------------------------------------------------------
# Jobs
# ------------------------------------------------------------

@dataclass
class Job:
    job_id: str
    document_id: str
    source: str
    filename: str
    extension: str
    size_bytes: int
    checksum: str
    customer_id: str
    loan_id: str | None
    status: str = "uploaded"
    step: str = "queued"
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    started_at: str | None = None
    finished_at: str | None = None
    attempts: int = 0
    error: str | None = None
    warnings: list[str] = field(default_factory=list)
    document_type: str | None = None
    chunk_count: int | None = None
    # One entry per name in STAGES: status is pending, running, completed or failed.
    stages: list[dict] = field(default_factory=new_stages)
    failed_stage: str | None = None
    # Whether running the job again could succeed (set when it fails).
    retryable: bool = False
    # When the latest attempt was queued: the upload time, or the retry time.
    queued_at: str | None = None

    def stage(self, name: str) -> dict:
        return next(stage for stage in self.stages if stage["name"] == name)

    def public(self) -> dict:
        """Fields safe to return to clients (no filesystem paths)."""
        data = asdict(self)
        data.pop("source")
        data["checksum"] = self.checksum[:16]
        data["step_index"] = STEPS.index(self.step) if self.step in STEPS else 0
        data["step_count"] = len(STEPS) - 1
        # Latest attempt: queued → finished (or until now while still running).
        # Time a failed job spent waiting before a retry is not included.
        data["duration_ms"] = _elapsed_ms(self.queued_at or self.created_at, self.finished_at or _now())
        return data


class JobRegistry:
    """Jobs in memory, mirrored to <upload dir>/<job_id>/job.json."""

    def __init__(self, upload_dir: Path):
        self.upload_dir = Path(upload_dir)
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._load()

    def _path(self, job_id: str) -> Path:
        return self.upload_dir / job_id / "job.json"

    def _load(self) -> None:
        if not self.upload_dir.exists():
            return
        for path in sorted(self.upload_dir.glob("*/job.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                migrated = "stages" not in data
                job = Job(**data)
            except (OSError, ValueError, TypeError):
                logger.warning(json.dumps({"event": "job_unreadable", "job_dir": path.parent.name}))
                continue
            if migrated:
                _migrate_legacy_job(job)
            if job.status in ("uploaded", "processing"):
                # The in-memory queue did not survive the restart.
                running = next((s for s in job.stages if s["status"] == "running"), None)
                if running:
                    running.update(status="failed", finished_at=_now(),
                                   error="Interrupted by a server restart.")
                job.status = "failed"
                job.failed_stage = running["name"] if running else None
                job.error = "Processing was interrupted by a server restart. Retry the job."
                job.retryable = True
                job.finished_at = job.updated_at = _now()
                self._write(job)
            elif migrated:
                self._write(job)
            self._jobs[job.job_id] = job

    def _write(self, job: Job) -> None:
        path = self._path(job.job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            json.dump(asdict(job), file, indent=2)
        os.replace(temp_name, path)

    def save(self, job: Job) -> None:
        with self._lock:
            job.updated_at = _now()
            self._jobs[job.job_id] = job
            self._write(job)

    def get(self, job_id: str) -> Job | None:
        if not JOB_ID_PATTERN.fullmatch(job_id or ""):
            return None
        with self._lock:
            return self._jobs.get(job_id)

    def all(self) -> list[Job]:
        with self._lock:
            return list(self._jobs.values())

    def find_duplicate(self, checksum: str, customer_id: str, loan_id: str | None) -> Job | None:
        with self._lock:
            matches = [
                job for job in self._jobs.values()
                if job.checksum == checksum and job.customer_id == customer_id and job.loan_id == loan_id
            ]
        # Prefer a job that is ready or in progress over a failed one.
        matches.sort(key=lambda job: (job.status == "failed", job.created_at))
        return matches[0] if matches else None


def _migrate_legacy_job(job: Job) -> None:
    """Give jobs recorded before per-stage tracking a stage list."""
    old_steps = {"validating": "normalization", "verifying": "indexing"}
    job.step = old_steps.get(job.step, job.step)
    job.stage("validation").update(status="completed", finished_at=job.created_at)

    if job.status == "ready":
        for stage in job.stages:
            stage["status"] = "completed"
    elif job.status == "failed" and job.step in STAGES:
        index = STAGES.index(job.step)
        for stage in job.stages[1:index]:
            stage["status"] = "completed"
        job.stages[index].update(status="failed", error=job.error)
        job.failed_stage = job.step
        job.retryable = True  # the original cause was not recorded


# ------------------------------------------------------------
# Service
# ------------------------------------------------------------

class IngestionService:
    def __init__(
        self,
        upload_dir: Path = UPLOAD_DIR,
        store: ProcessedStore | None = None,
        library: DocumentLibrary | None = None,
        max_upload_bytes: int = MAX_UPLOAD_BYTES,
        executor: Executor | None = None,
    ):
        self.upload_dir = Path(upload_dir)
        self.store = store or ProcessedStore()
        self.library = library or DocumentLibrary(self.store.documents_path, self.store.chunks_path)
        self.max_upload_bytes = max_upload_bytes
        self.jobs = JobRegistry(self.upload_dir)
        # One worker: jobs run in order and never write the files concurrently.
        self.executor = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix="ingestion")

    # ---- options -------------------------------------------------

    def options(self) -> dict:
        names_to_customers, loans_to_customers = load_verified_entities()
        customers = sorted(set(names_to_customers.values()) | set(loans_to_customers.values()))
        return {
            "allowed_extensions": sorted(ALLOWED_EXTENSIONS),
            "max_upload_bytes": self.max_upload_bytes,
            "customers": customers,
            "loans": [
                {"loan_id": loan, "customer_id": customer}
                for loan, customer in sorted(loans_to_customers.items())
            ],
        }

    # ---- submit --------------------------------------------------

    def _source_for(self, job_id: str, filename: str) -> str:
        path = (self.upload_dir / job_id / filename).resolve()
        try:
            return normalize_source(str(path.relative_to(PROJECT_ROOT)))
        except ValueError:
            # Upload directory outside the project: use a logical path.
            return f"uploads/{job_id}/{filename}"

    def submit(
        self,
        data: bytes,
        original_filename: str,
        customer_id: str,
        loan_id: str | None,
    ) -> tuple[Job, bool]:
        """Validate and store an upload, then queue it. Returns (job, duplicate)."""
        validation_started = _now()
        filename = safe_filename(original_filename)
        extension = Path(filename).suffix.lower()

        if extension not in ALLOWED_EXTENSIONS:
            allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
            raise UploadRejected(f"Unsupported file type '{extension or 'none'}'. Allowed: {allowed}.", 415)
        if not data:
            raise UploadRejected("The file is empty.", 400)
        if len(data) > self.max_upload_bytes:
            raise UploadRejected(
                f"The file is larger than the {self.max_upload_bytes // (1024 * 1024)} MB limit.", 413
            )

        check_content(ALLOWED_EXTENSIONS[extension], data)
        customer_id, loan_id = validate_identifiers(customer_id, loan_id)
        checksum = hashlib.sha256(data).hexdigest()

        existing = self.jobs.find_duplicate(checksum, customer_id, loan_id)
        if existing is not None:
            # Re-uploading a file whose job failed for a temporary reason retries
            # it; a permanent failure is returned as it is.
            if existing.status == "failed" and existing.retryable:
                self.retry(existing.job_id)
            return existing, True

        job_id = uuid.uuid4().hex
        source = self._source_for(job_id, filename)
        job_dir = self.upload_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=False)
        (job_dir / filename).write_bytes(data)

        job = Job(
            job_id=job_id,
            document_id=stable_document_id(source, None),
            source=source,
            filename=filename,
            extension=extension,
            size_bytes=len(data),
            checksum=checksum,
            customer_id=customer_id,
            loan_id=loan_id,
        )
        validation_finished = _now()
        job.stage("validation").update(
            status="completed",
            started_at=validation_started,
            finished_at=validation_finished,
            duration_ms=_elapsed_ms(validation_started, validation_finished),
        )
        self.jobs.save(job)
        logger.info(json.dumps({"event": "upload_accepted", "job_id": job_id, "extension": extension,
                                "size_bytes": len(data)}))
        self.executor.submit(self._run, job_id)
        return job, False

    def retry(self, job_id: str) -> Job:
        job = self.jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        if job.status != "failed":
            raise UploadRejected(f"Only failed jobs can be retried (this job is {job.status}).", 409)
        if not job.retryable:
            raise UploadRejected(
                "This job cannot be retried: running it again would fail the same way. "
                "Fix the file or the customer/loan selection and upload it again.",
                409,
            )
        job.status, job.step, job.error, job.warnings = "uploaded", "queued", None, []
        job.started_at = job.finished_at = job.failed_stage = None
        job.queued_at = _now()
        job.retryable = False
        for stage in job.stages[1:]:  # upload validation stays completed
            stage.update(status="pending", started_at=None, finished_at=None, duration_ms=None, error=None)
        self.jobs.save(job)
        self.executor.submit(self._run, job_id)
        return job

    # ---- listing and consistency -----------------------------------

    def reconcile(self) -> None:
        """
        Keep job status consistent with the index: a "ready" job whose
        document is no longer in the processed data (for example after a
        batch rebuild) is marked failed and retryable, so it can be re-indexed
        from the stored original.
        """
        for job in self.jobs.all():
            if job.status != "ready":
                continue
            try:
                indexed = self.library.get(job.document_id) is not None
            except Exception:
                return  # the library cannot be read; do not change any job
            if not indexed:
                job.status, job.failed_stage, job.retryable = "failed", "indexing", True
                job.error = (
                    "The document is no longer in the search index (the processed data may "
                    "have been rebuilt). Retry to index it again."
                )
                job.stage("indexing").update(status="failed", error=job.error)
                self.jobs.save(job)

    def list_jobs(
        self,
        status: str | None = None,
        customer_id: str | None = None,
        document_type: str | None = None,
    ) -> list[Job]:
        """Jobs matching the filters, newest first."""
        self.reconcile()
        jobs = [
            job for job in self.jobs.all()
            if (not status or job.status == status)
            and (not customer_id or job.customer_id == customer_id)
            and (not document_type or job.document_type == document_type)
        ]
        return sorted(jobs, key=lambda job: (job.created_at, job.job_id), reverse=True)

    # ---- processing ------------------------------------------------

    @contextmanager
    def _stage(self, job: Job, name: str):
        """Run one stage, recording its status, timestamps and duration."""
        stage = job.stage(name)
        started = time.perf_counter()
        stage.update(status="running", started_at=_now(), finished_at=None, error=None)
        job.step = name
        self.jobs.save(job)
        try:
            yield
        except Exception as exc:
            stage.update(status="failed", finished_at=_now(),
                         duration_ms=round((time.perf_counter() - started) * 1000, 1),
                         error=_safe_message(exc))
            raise
        stage.update(status="completed", finished_at=_now(),
                     duration_ms=round((time.perf_counter() - started) * 1000, 1))
        self.jobs.save(job)

    def _run(self, job_id: str) -> None:
        job = self.jobs.get(job_id)
        if job is None:
            return

        job.status, job.attempts, job.started_at = "processing", job.attempts + 1, _now()
        written = False

        try:
            with self._stage(job, "parsing"):
                parsed = self._parse(job)

            with self._stage(job, "normalization"):
                document = self._normalize(job, parsed)
                self._check_identifiers(job, document)

            with self._stage(job, "chunking"):
                chunks = self._chunk(document)

            with self._stage(job, "embedding"):
                embeddings = self._embed(chunks)

            # Ready requires the records to be written AND visible to every reader.
            with self._stage(job, "indexing"):
                written = True
                self.store.upsert_source(job.source, [document.to_dict()], chunks, embeddings)
                self._verify(job, chunks)

        except Exception as exc:
            if written:
                # Never leave a half-ingested document visible.
                self.store.remove_source(job.source)
            job.status, job.finished_at = "failed", _now()
            job.error = _safe_message(exc)
            job.failed_stage = job.step
            job.retryable = exc.retryable if isinstance(exc, ProcessingError) else True
            self.jobs.save(job)
            logger.warning(json.dumps({"event": "ingestion_failed", "job_id": job_id, "stage": job.step,
                                       "error_type": type(exc).__name__}))
            return

        job.status, job.step, job.finished_at = "ready", "done", _now()
        job.chunk_count = len(chunks)
        self.jobs.save(job)
        logger.info(json.dumps({"event": "ingestion_ready", "job_id": job_id, "chunks": len(chunks)}))

    def _parse(self, job: Job) -> dict:
        """Extract text with the existing parser for the file type."""
        from src.pipeline import IngestionPipeline

        path = self.upload_dir / job.job_id / job.filename
        parser_class = IngestionPipeline.PARSERS.get(job.extension)
        if parser_class is None:
            raise ProcessingError(f"No parser for {job.extension} files.", retryable=False)
        try:
            result = parser_class().parse(path)
        except Exception as exc:
            raise ProcessingError(
                f"The file could not be read as {job.extension.lstrip('.').upper()} ({type(exc).__name__}).",
                retryable=False,
            ) from exc

        if not str(result.get("content") or "").strip():
            raise ProcessingError(
                "No text could be extracted from this file. Scanned images are not supported.",
                retryable=False,
            )
        return result

    def _normalize(self, job: Job, parsed: dict):
        """Classify, extract metadata and validate with the existing pipeline."""
        from src.pipeline import IngestionPipeline
        from src.validation.validator import DocumentValidator

        document = IngestionPipeline()._normalize_document(parsed)

        # The parser records the absolute on-disk path; store the project-relative source instead.
        document.source = job.source
        document.metadata["upload"] = {"job_id": job.job_id, "filename": job.filename,
                                       "checksum_sha256": job.checksum}
        job.document_type = document.document_type

        validation = DocumentValidator().validate(document)
        job.warnings = (validation.warnings + validation.errors)[:10]
        return document

    def _check_identifiers(self, job: Job, document) -> None:
        """
        Identifiers found in the document's text must agree with the upload.
        Missing identifiers are filled from the upload form.
        """
        _, loans_to_customers = load_verified_entities()
        stated_customer = document.customer_id
        stated_loan = document.loan_id

        if stated_customer and stated_customer != job.customer_id:
            raise ProcessingError(
                f"The document refers to customer {stated_customer}, but it was uploaded for {job.customer_id}.",
                retryable=False,
            )
        if stated_loan and job.loan_id and stated_loan != job.loan_id:
            raise ProcessingError(
                f"The document refers to loan {stated_loan}, but it was uploaded for {job.loan_id}.",
                retryable=False,
            )
        if stated_loan and not job.loan_id and loans_to_customers.get(stated_loan) not in (None, job.customer_id):
            raise ProcessingError(
                f"The document refers to loan {stated_loan}, which belongs to a different customer.",
                retryable=False,
            )

        document.customer_id = job.customer_id
        document.loan_id = stated_loan or job.loan_id

    def _chunk(self, document) -> list[dict]:
        texts = RecursiveChunker(chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP).chunk(document.content)
        chunks = [
            asdict(DocumentChunk(
                chunk_id=str(uuid.uuid4()),
                document_id=document.document_id,
                loan_id=document.loan_id,
                customer_id=document.customer_id,
                document_type=document.document_type,
                source=document.source,
                chunk_index=index,
                content=text,
            ))
            for index, text in enumerate(texts)
            if text.strip()
        ]
        if not chunks:
            raise ProcessingError("The extracted text produced no searchable chunks.", retryable=False)
        return chunks

    def _embed(self, chunks: list[dict]) -> list[dict]:
        from src.embeddings.semantic_search import get_embedding_model

        vectors = get_embedding_model().encode([chunk["content"] for chunk in chunks])
        return [
            {**chunk, "embedding": [float(value) for value in vector]}
            for chunk, vector in zip(chunks, vectors)
        ]

    def _verify(self, job: Job, chunks: list[dict]) -> None:
        """Ready only when every reader can actually see the new document."""
        from src.embeddings import semantic_search
        from src.retrieval import exact_search

        document = self.library.get(job.document_id)
        if document is None or len(document.chunks) != len(chunks):
            raise ProcessingError("The document did not appear in the document library.")

        store = semantic_search.get_chunk_store()
        indexed = {chunk.get("chunk_id") for chunk in store.chunks}
        if not all(chunk["chunk_id"] in indexed for chunk in chunks):
            raise ProcessingError("The document's chunks did not appear in semantic search.")

        exact_store = ProcessedStore(documents_path=exact_search.DOCUMENTS_PATH)
        if not exact_store.contains_source(job.source):
            raise ProcessingError("The document did not appear in exact search.")
