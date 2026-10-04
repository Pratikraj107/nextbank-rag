import json
import uuid
from dataclasses import asdict
from pathlib import Path

from src.chunking.recursive import RecursiveChunker
from src.models.chunk import DocumentChunk


def process_documents(
    input_path: str = "data/processed/documents.jsonl",
    output_path: str = "data/processed/chunks.jsonl",
) -> None:
    chunker = RecursiveChunker(chunk_size=200, overlap=50)

    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    document_count = 0
    chunk_count = 0

    with open(input_path, "r", encoding="utf-8") as source:
        with open(output_file, "w", encoding="utf-8") as destination:
            for line in source:
                if not line.strip():
                    continue

                document = json.loads(line)
                document_count += 1

                text_chunks = chunker.chunk(document["content"])

                for index, content in enumerate(text_chunks):
                    chunk = DocumentChunk(
                        chunk_id=str(uuid.uuid4()),
                        document_id=document["document_id"],
                        loan_id=document.get("loan_id"),
                        customer_id=document.get("customer_id"),
                        document_type=document["document_type"],
                        source=document["source"],
                        chunk_index=index,
                        content=content,
                    )

                    destination.write(
                        json.dumps(asdict(chunk), ensure_ascii=False) + "\n"
                    )

                    chunk_count += 1

    print(f"Documents processed: {document_count}")
    print(f"Chunks created: {chunk_count}")
    print(f"Output: {output_file}")


if __name__ == "__main__":
    process_documents()