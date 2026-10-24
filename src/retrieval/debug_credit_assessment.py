import json
from pathlib import Path

INPUT_FILE = Path("data/processed/chunk_embeddings.jsonl")
EXPECTED_FILENAME = "10_credit_assessment.html"


def main():
    if not INPUT_FILE.exists():
        print(f"File not found: {INPUT_FILE}")
        return

    all_chunks = []

    with INPUT_FILE.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                all_chunks.append(json.loads(line))

    print(f"Total chunks loaded: {len(all_chunks)}")

    print("\n1. SEARCHING FOR THE EXPECTED HTML SOURCE")
    print("=" * 80)

    matching_chunks = [
        chunk
        for chunk in all_chunks
        if EXPECTED_FILENAME.lower()
        in str(chunk.get("source", "")).lower()
    ]

    if not matching_chunks:
        print("No chunks found for the expected HTML source.")
        print("The HTML document may not have been ingested,")
        print("or its source path may not contain the expected filename.")
    else:
        print(f"Matching chunks: {len(matching_chunks)}")

        for chunk in matching_chunks:
            print("\nSource:", chunk.get("source"))
            print("Document type:", chunk.get("document_type"))
            print("Customer ID:", chunk.get("customer_id"))
            print("Loan ID:", chunk.get("loan_id"))
            print("Chunk index:", chunk.get("chunk_index"))
            print("Content:", chunk.get("content", "")[:500])

    print("\n2. ALL CREDIT-ASSESSMENT CHUNKS")
    print("=" * 80)

    assessment_chunks = [
        chunk
        for chunk in all_chunks
        if chunk.get("document_type") == "credit_assessment"
    ]

    print(f"Total credit_assessment chunks: {len(assessment_chunks)}")

    for chunk in assessment_chunks:
        print("\nSource:", chunk.get("source"))
        print("Customer ID:", chunk.get("customer_id"))
        print("Loan ID:", chunk.get("loan_id"))
        print("Chunk index:", chunk.get("chunk_index"))
        print("Content:", chunk.get("content", "")[:250])

    print("\n3. CHUNKS MATCHING THE CURRENT FILTERS")
    print("=" * 80)

    filtered_chunks = [
        chunk
        for chunk in all_chunks
        if chunk.get("customer_id") == "NB-CUST-3001"
        and chunk.get("document_type") == "credit_assessment"
    ]

    print(f"Matching filtered chunks: {len(filtered_chunks)}")

    for chunk in filtered_chunks:
        print(
            f"{chunk.get('source')} | "
            f"customer={chunk.get('customer_id')} | "
            f"type={chunk.get('document_type')} | "
            f"chunk={chunk.get('chunk_index')}"
        )


if __name__ == "__main__":
    main()