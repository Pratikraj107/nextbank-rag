"""
Read-only, in-memory view of the processed document library.

Data comes only from the two processed JSONL files produced by ingestion
and chunking. Nothing here reads user-supplied paths.

Document IDs
------------
`document_id` in documents.jsonl is a random UUID regenerated on every
ingestion run, so it cannot be used in URLs that should survive
re-ingestion. Each document instead gets a stable ID derived from its
normalised source path (plus the row number for CSV rows, where one file
yields one document per row):

    doc_ + first 16 hex chars of sha256("<source>#row=<row>")

IDs are validated against that exact shape before lookup, so a request can
never be interpreted as a path.

Caching
-------
The files are parsed once and kept in memory. Every access checks the files'
modification time and size; if either changed (ingestion or chunking was
re-run), the library is rebuilt on the next request. Restarting the API also
reloads it.
"""

import hashlib
import json
import os
import re
import threading
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DOCUMENTS_PATH = PROJECT_ROOT / "data" / "processed" / "documents.jsonl"
DEFAULT_CHUNKS_PATH = PROJECT_ROOT / "data" / "processed" / "chunks.jsonl"

DOCUMENT_ID_PATTERN = re.compile(r"^doc_[0-9a-f]{16}$")

REQUIRED_DOCUMENT_FIELDS = ("document_id", "source", "content")
REQUIRED_CHUNK_FIELDS = ("document_id", "chunk_index", "content")


class DocumentLibraryError(RuntimeError):
    """The processed data is missing, malformed, or inconsistent."""


@dataclass(frozen=True)
class Chunk:
    chunk_id: str | None
    chunk_index: int
    content: str
    document_type: str | None
    customer_id: str | None
    loan_id: str | None


@dataclass
class Document:
    id: str
    source: str
    filename: str
    source_type: str | None
    document_type: str | None
    customer_id: str | None
    loan_id: str | None
    row_number: int | None
    content: str
    metadata: dict[str, Any]
    chunks: list[Chunk] = field(default_factory=list)


def normalize_source(source: str) -> str:
    """Use forward slashes so IDs match across operating systems."""
    return str(PurePosixPath(source.replace("\\", "/")))


def stable_document_id(source: str, row_number: int | None) -> str:
    key = f"{normalize_source(source)}#row={row_number if row_number is not None else ''}"
    return "doc_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def is_valid_document_id(document_id: str) -> bool:
    return bool(DOCUMENT_ID_PATTERN.fullmatch(document_id))


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _read_jsonl(path: Path, required: tuple[str, ...], label: str) -> list[dict]:
    if not path.is_file():
        raise DocumentLibraryError(
            f"{label} file not found ({path.name}). Run ingestion and chunking first."
        )

    records = []

    with path.open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise DocumentLibraryError(
                    f"{label} file {path.name} has invalid JSON on line {line_number}."
                ) from exc
            if not isinstance(record, dict):
                raise DocumentLibraryError(
                    f"{label} file {path.name} line {line_number} is not a JSON object."
                )
            missing = [name for name in required if record.get(name) is None]
            if missing:
                raise DocumentLibraryError(
                    f"{label} file {path.name} line {line_number} is missing {missing}."
                )
            records.append(record)

    return records


def build_documents(document_records: list[dict], chunk_records: list[dict]) -> list[Document]:
    """Turn raw JSONL records into documents with their chunks attached."""
    documents: list[Document] = []
    by_ingestion_id: dict[str, Document] = {}
    seen_ids: set[str] = set()

    for record in document_records:
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        row_number = metadata.get("row_number") if isinstance(metadata.get("row_number"), int) else None
        source = normalize_source(str(record["source"]))
        document_id = stable_document_id(source, row_number)

        if document_id in seen_ids:
            raise DocumentLibraryError(
                f"Two documents share the source '{source}' and row {row_number}; "
                "cannot assign stable IDs."
            )
        seen_ids.add(document_id)

        document = Document(
            id=document_id,
            source=source,
            filename=PurePosixPath(source).name,
            source_type=_optional_str(record.get("source_type")),
            document_type=_optional_str(record.get("document_type")),
            customer_id=_optional_str(record.get("customer_id")),
            loan_id=_optional_str(record.get("loan_id")),
            row_number=row_number,
            content=str(record.get("content") or ""),
            metadata=metadata,
        )
        documents.append(document)
        by_ingestion_id[str(record["document_id"])] = document

    orphaned = 0
    chunks_by_document: dict[str, list[Chunk]] = defaultdict(list)

    for record in chunk_records:
        document = by_ingestion_id.get(str(record["document_id"]))
        if document is None:
            orphaned += 1
            continue
        chunks_by_document[document.id].append(
            Chunk(
                chunk_id=_optional_str(record.get("chunk_id")),
                chunk_index=int(record["chunk_index"]),
                content=str(record["content"]),
                document_type=_optional_str(record.get("document_type")),
                customer_id=_optional_str(record.get("customer_id")),
                loan_id=_optional_str(record.get("loan_id")),
            )
        )

    # Chunk files from a different ingestion run reference IDs that no longer
    # exist. Showing those documents with zero chunks would be misleading.
    if orphaned:
        raise DocumentLibraryError(
            f"{orphaned} chunk(s) reference documents that are not in documents.jsonl. "
            "The chunk file is out of date: re-run chunking after ingestion."
        )

    for document in documents:
        document.chunks = sorted(chunks_by_document.get(document.id, []), key=lambda c: c.chunk_index)

    # Deterministic order: by source path, then CSV row.
    documents.sort(key=lambda d: (d.source, d.row_number if d.row_number is not None else -1))
    return documents


@dataclass(frozen=True)
class DocumentQuery:
    search: str | None = None
    document_type: str | None = None
    customer_id: str | None = None
    loan_id: str | None = None
    page: int = 1
    page_size: int = 25


class DocumentLibrary:
    """Thread-safe cache of the processed documents and chunks."""

    def __init__(
        self,
        documents_path: Path = DEFAULT_DOCUMENTS_PATH,
        chunks_path: Path = DEFAULT_CHUNKS_PATH,
    ):
        self.documents_path = Path(documents_path)
        self.chunks_path = Path(chunks_path)
        self._lock = threading.Lock()
        self._signature: tuple | None = None
        self._documents: list[Document] = []
        self._by_id: dict[str, Document] = {}

    def _current_signature(self) -> tuple:
        signature = []
        for path in (self.documents_path, self.chunks_path):
            try:
                stat = os.stat(path)
                signature.append((stat.st_mtime_ns, stat.st_size))
            except FileNotFoundError:
                signature.append(None)
        return tuple(signature)

    def _ensure_loaded(self) -> None:
        signature = self._current_signature()
        if signature == self._signature:
            return

        with self._lock:
            if signature == self._signature:
                return
            documents = build_documents(
                _read_jsonl(self.documents_path, REQUIRED_DOCUMENT_FIELDS, "Documents"),
                _read_jsonl(self.chunks_path, REQUIRED_CHUNK_FIELDS, "Chunks"),
            )
            self._documents = documents
            self._by_id = {document.id: document for document in documents}
            self._signature = signature

    def all(self) -> list[Document]:
        self._ensure_loaded()
        return self._documents

    def get(self, document_id: str) -> Document | None:
        if not is_valid_document_id(document_id):
            return None
        self._ensure_loaded()
        return self._by_id.get(document_id)

    def search(self, query: DocumentQuery) -> tuple[list[Document], int]:
        """Return (one page of matching documents, total matching count)."""
        documents = self.all()
        needle = (query.search or "").strip().lower()

        matches = [
            d for d in documents
            if (not needle or needle in d.filename.lower() or needle in d.source.lower())
            and (not query.document_type or d.document_type == query.document_type)
            and (not query.customer_id or d.customer_id == query.customer_id)
            and (not query.loan_id or d.loan_id == query.loan_id)
        ]

        start = (query.page - 1) * query.page_size
        return matches[start:start + query.page_size], len(matches)

    def facets(self) -> dict[str, list[dict]]:
        """Distinct filter values with counts, from the whole library."""
        documents = self.all()

        def counts(values) -> list[dict]:
            return [
                {"value": value, "count": count}
                for value, count in sorted(Counter(v for v in values if v).items())
            ]

        return {
            "document_types": counts(d.document_type for d in documents),
            "customer_ids": counts(d.customer_id for d in documents),
            "loan_ids": counts(d.loan_id for d in documents),
        }
