import json
from pathlib import Path

from sentence_transformers import SentenceTransformer


INPUT_FILE = "data/processed/chunks.jsonl"
OUTPUT_FILE = "data/processed/chunk_embeddings.jsonl"
MODEL_NAME = "BAAI/bge-base-en-v1.5"


def main():
    print("Loading embedding model...")
    model = SentenceTransformer(MODEL_NAME)

    with open(INPUT_FILE, "r", encoding="utf-8") as file:
        chunks = [
            json.loads(line)
            for line in file
            if line.strip()
        ]

    print(f"Chunks loaded: {len(chunks)}")

    texts = [
        chunk["content"]
        for chunk in chunks
    ]

    print("Generating embeddings...")

    embeddings = model.encode(
        texts,
        show_progress_bar=True
    )

    output_path = Path(OUTPUT_FILE)
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with open(
        output_path,
        "w",
        encoding="utf-8"
    ) as file:

        for chunk, embedding in zip(
            chunks,
            embeddings
        ):
            record = {
                "chunk_id": chunk["chunk_id"],
                "document_id": chunk["document_id"],
                "loan_id": chunk["loan_id"],
                "customer_id": chunk["customer_id"],
                "document_type": chunk["document_type"],
                "source": chunk["source"],
                "chunk_index": chunk["chunk_index"],
                "content": chunk["content"],
                "embedding": embedding.tolist(),
            }

            file.write(
                json.dumps(record)
                + "\n"
            )

    print()
    print(f"Embeddings created: {len(embeddings)}")
    print(f"Embedding dimensions: {len(embeddings[0])}")
    print(f"Output: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()