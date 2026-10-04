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

    print(f"Total chunks: {len(chunks)}")
    print("=" * 80)

 

    # Show employment agreement chunks
    employment_chunks = [
        chunk
        for chunk in chunks
        if chunk["document_type"] == "employment_agreement"
    ]

    for chunk in employment_chunks:
        print(f"\nEmployment chunk: {chunk['chunk_id']}")
        print(chunk["content"])


if __name__ == "__main__":
    main()