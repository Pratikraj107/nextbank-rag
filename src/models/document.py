from dataclasses import dataclass, field
from typing import Any


@dataclass
class NormalizedDocument:
    """Common representation of any document entering the ingestion pipeline."""

    document_id: str
    loan_id: str | None
    customer_id: str | None

    document_type: str
    source: str
    source_type: str

    content: str
    language: str | None = None

    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert the document into a JSON-serializable dictionary."""
        return {
            "document_id": self.document_id,
            "loan_id": self.loan_id,
            "customer_id": self.customer_id,
            "document_type": self.document_type,
            "source": self.source,
            "source_type": self.source_type,
            "content": self.content,
            "language": self.language,
            "metadata": self.metadata,
        }