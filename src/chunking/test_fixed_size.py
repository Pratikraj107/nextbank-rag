import json

from src.chunking.recursive import RecursiveChunker


def main():
    # Load normalized documents
    with open(
        "data/processed/documents.jsonl",
        "r",
        encoding="utf-8"
    ) as file:
        documents = [
            json.loads(line)
            for line in file
        ]

    # Find one employment agreement
    document = next(
        doc
        for doc in documents
        if doc["document_type"] == "employment_agreement"
    )

    print(f"Document ID: {document['document_id']}")
    print(f"Document Type: {document['document_type']}")
    print(f"Source: {document['source']}")
    print()

    # Recursive chunker with overlap
    chunker = RecursiveChunker(
        chunk_size=200,
        overlap=50
    )

    chunks = chunker.chunk(
        document["content"]
    )

    print(f"Total chunks: {len(chunks)}")
    print("=" * 80)

    for index, chunk in enumerate(chunks):
        print(f"\nCHUNK {index}")
        print(f"Characters: {len(chunk)}")
        print("-" * 40)
        print(chunk)


if __name__ == "__main__":
    main()