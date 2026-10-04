import json


def main():
    with open(
        "data/processed/chunks.jsonl",
        "r",
        encoding="utf-8"
    ) as file:
        chunks = [
            json.loads(line)
            for line in file
        ]

    sizes = [
        len(chunk["content"])
        for chunk in chunks
    ]

    document_ids = {
        chunk["document_id"]
        for chunk in chunks
    }

    print(f"Documents represented: {len(document_ids)}")
    print(f"Total chunks: {len(chunks)}")
    print(f"Average chunks/document: {len(chunks) / len(document_ids):.2f}")
    print(f"Average chunk size: {sum(sizes) / len(sizes):.2f} characters")
    print(f"Minimum chunk size: {min(sizes)} characters")
    print(f"Maximum chunk size: {max(sizes)} characters")


if __name__ == "__main__":
    main()