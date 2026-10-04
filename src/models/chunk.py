from dataclasses import dataclass


@dataclass
class DocumentChunk:
    chunk_id: str
    document_id: str
    loan_id: str | None
    customer_id: str | None
    document_type: str
    source: str
    chunk_index: int
    content: str