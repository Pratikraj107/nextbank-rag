import json

from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

from src.retrieval.query_analyzer import QueryAnalyzer


INPUT_FILE = "data/processed/chunk_embeddings.jsonl"
MODEL_NAME = "BAAI/bge-base-en-v1.5"


def load_chunks():
    """Load chunks and their precomputed embeddings from JSONL."""
    with open(INPUT_FILE, "r", encoding="utf-8") as file:
        return [
            json.loads(line)
            for line in file
            if line.strip()
        ]


def search(
    query: str,
    top_k: int = 5,
    customer_id: str | None = None,
    loan_id: str | None = None,
    document_type: str | None = None,
):
    """
    Search for relevant chunks using optional metadata filters
    followed by cosine-similarity ranking.
    """
    print("Loading embedding model...")

    model = SentenceTransformer(MODEL_NAME)
    chunks = load_chunks()

    # Step 1: Apply metadata filters when provided.
    if customer_id:
        chunks = [
            chunk for chunk in chunks
            if chunk.get("customer_id") == customer_id
        ]

    if loan_id:
        chunks = [
            chunk for chunk in chunks
            if chunk.get("loan_id") == loan_id
        ]

    if document_type:
        chunks = [
            chunk for chunk in chunks
            if chunk.get("document_type") == document_type
        ]

    print(f"Candidate chunks after filtering: {len(chunks)}")

    if not chunks:
        return []

    # Step 2: Embed the user's question.
    query_embedding = model.encode([query])

    # Step 3: Compare the question against stored chunk embeddings.
    chunk_embeddings = [
        chunk["embedding"]
        for chunk in chunks
    ]

    similarities = cosine_similarity(
        query_embedding,
        chunk_embeddings,
    )[0]

    # Step 4: Attach scores and rank the chunks.
    results = []

    for chunk, score in zip(chunks, similarities):
        results.append({
            "score": float(score),
            "chunk": chunk,
        })

    results.sort(
        key=lambda result: result["score"],
        reverse=True,
    )

    return results[:top_k]


def search_with_analysis(query: str, top_k: int = 5):
    """
    Analyze a natural-language question, infer metadata filters,
    and run semantic search automatically.
    """
    analyzer = QueryAnalyzer()
    analysis = analyzer.analyze(query)

    print("\nQUERY ANALYSIS")
    print("=" * 80)
    print(f"Original query: {analysis.original_query}")
    print(f"Intent: {analysis.intent}")
    print(f"Customer ID: {analysis.customer_id}")
    print(f"Loan ID: {analysis.loan_id}")
    print(f"Document type: {analysis.document_type}")
    print(f"Matched entities: {analysis.matched_entities}")

    # Use the analyzer's inferred filters.
    # Any field with value None is left unfiltered.
    results = search(
        query=query,
        top_k=top_k,
        customer_id=analysis.customer_id,
        loan_id=analysis.loan_id,
        document_type=analysis.document_type,
    )

    return results, analysis


def main():
    query = "What is Lotte van Dijk's annual salary?"

    results, analysis = search_with_analysis(
        query=query,
        top_k=5,
    )

    print("\nSEARCH RESULTS")
    print("=" * 80)

    if not results:
        print("No matching chunks found.")
        return

    for index, result in enumerate(results, start=1):
        chunk = result["chunk"]

        print(f"\nRESULT {index}")
        print(f"Similarity: {result['score']:.4f}")
        print(f"Document Type: {chunk.get('document_type')}")
        print(f"Loan ID: {chunk.get('loan_id')}")
        print(f"Customer ID: {chunk.get('customer_id')}")
        print(f"Source: {chunk.get('source')}")
        print(f"Chunk Index: {chunk.get('chunk_index')}")
        print("-" * 40)
        print(chunk.get("content", ""))


if __name__ == "__main__":
    main()