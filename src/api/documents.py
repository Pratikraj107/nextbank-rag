"""
Read-only document browsing endpoints for the Document Explorer.

These endpoints only read the processed JSONL files through
DocumentLibrary. They do not call the agent, the embedding model or the
LLM, and they never accept file paths. There is no authentication: this is
a local prototype on synthetic data.
"""

import math
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from src.documents.library import (
    Document,
    DocumentLibrary,
    DocumentLibraryError,
    DocumentQuery,
)

router = APIRouter(prefix="/api/documents", tags=["documents"])

_library = DocumentLibrary()


def get_document_library() -> DocumentLibrary:
    """Dependency; tests override it with a library built from fixtures."""
    return _library


MAX_PAGE_SIZE = 100


# ------------------------------------------------------------
# Response models
# ------------------------------------------------------------

class DocumentSummary(BaseModel):
    id: str
    filename: str
    source: str
    source_type: str | None
    document_type: str | None
    customer_id: str | None
    loan_id: str | None
    # Only set for CSV rows, where one file holds several documents.
    row_number: int | None
    chunk_count: int


class FacetValue(BaseModel):
    value: str
    count: int


class DocumentFacets(BaseModel):
    document_types: list[FacetValue]
    customer_ids: list[FacetValue]
    loan_ids: list[FacetValue]


class DocumentListResponse(BaseModel):
    items: list[DocumentSummary]
    # Documents matching the filters.
    total: int
    # Documents in the whole library, regardless of filters.
    library_total: int
    page: int
    page_size: int
    total_pages: int
    # Filter values available across the whole library, not just this page.
    facets: DocumentFacets


class DocumentDetail(DocumentSummary):
    content: str
    # Fields extracted during ingestion, as stored (e.g. classification,
    # email headers, CSV record values). Keys vary by document type.
    metadata: dict[str, Any]


class ChunkResponse(BaseModel):
    chunk_id: str | None
    chunk_index: int
    content: str
    document_type: str | None
    customer_id: str | None
    loan_id: str | None


class DocumentChunksResponse(BaseModel):
    document_id: str
    total: int
    chunks: list[ChunkResponse]


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

def _summary(document: Document) -> DocumentSummary:
    return DocumentSummary(
        id=document.id,
        filename=document.filename,
        source=document.source,
        source_type=document.source_type,
        document_type=document.document_type,
        customer_id=document.customer_id,
        loan_id=document.loan_id,
        row_number=document.row_number,
        chunk_count=len(document.chunks),
    )


def _unavailable(exc: DocumentLibraryError) -> HTTPException:
    # The message names the file and the problem, never a full path.
    return HTTPException(status_code=503, detail=f"Document library unavailable: {exc}")


def _get_or_404(library: DocumentLibrary, document_id: str) -> Document:
    try:
        document = library.get(document_id)
    except DocumentLibraryError as exc:
        raise _unavailable(exc) from exc

    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    return document


def _clean(value: str | None) -> str | None:
    return value.strip() or None if value is not None else None


# ------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------

@router.get("", response_model=DocumentListResponse)
def list_documents(
    q: str | None = Query(default=None, max_length=200, description="Search filename or source path"),
    document_type: str | None = Query(default=None, max_length=100),
    customer_id: str | None = Query(default=None, max_length=100),
    loan_id: str | None = Query(default=None, max_length=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=MAX_PAGE_SIZE),
    library: DocumentLibrary = Depends(get_document_library),
):
    query = DocumentQuery(
        search=_clean(q),
        document_type=_clean(document_type),
        customer_id=_clean(customer_id),
        loan_id=_clean(loan_id),
        page=page,
        page_size=page_size,
    )

    try:
        documents, total = library.search(query)
        facets = library.facets()
        library_total = len(library.all())
    except DocumentLibraryError as exc:
        raise _unavailable(exc) from exc

    return DocumentListResponse(
        items=[_summary(document) for document in documents],
        total=total,
        library_total=library_total,
        page=page,
        page_size=page_size,
        total_pages=max(1, math.ceil(total / page_size)),
        facets=DocumentFacets(**facets),
    )


@router.get("/{document_id}", response_model=DocumentDetail)
def get_document(
    document_id: str,
    library: DocumentLibrary = Depends(get_document_library),
):
    document = _get_or_404(library, document_id)

    return DocumentDetail(
        **_summary(document).model_dump(),
        content=document.content,
        metadata=document.metadata,
    )


@router.get("/{document_id}/chunks", response_model=DocumentChunksResponse)
def get_document_chunks(
    document_id: str,
    library: DocumentLibrary = Depends(get_document_library),
):
    document = _get_or_404(library, document_id)

    return DocumentChunksResponse(
        document_id=document.id,
        total=len(document.chunks),
        chunks=[
            ChunkResponse(
                chunk_id=chunk.chunk_id,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                document_type=chunk.document_type,
                customer_id=chunk.customer_id,
                loan_id=chunk.loan_id,
            )
            for chunk in document.chunks
        ],
    )
