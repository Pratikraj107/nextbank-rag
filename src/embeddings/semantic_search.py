import json
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass

import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

from src.observability.timing import timed_stage
from src.retrieval.query_analyzer import QueryAnalysis, QueryAnalyzer


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


# ============================================================
# LOAD-ONCE RESOURCES
# ============================================================

_model: SentenceTransformer | None = None
_model_lock = threading.Lock()


def get_embedding_model() -> SentenceTransformer:
    """Load the embedding model once per process and reuse it."""
    global _model

    if _model is None:
        with _model_lock:
            if _model is None:
                with timed_stage("embedding_model_load"):
                    _model = SentenceTransformer(MODEL_NAME)

    return _model


@dataclass(frozen=True)
class ChunkStore:
    # (mtime_ns, size) of INPUT_FILE when it was loaded.
    signature: tuple[int, int]
    chunks: list[dict]
    # One row per chunk, in the same order as `chunks`.
    embeddings: np.ndarray


_store: ChunkStore | None = None
_store_lock = threading.Lock()


def get_chunk_store() -> ChunkStore:
    """
    Load chunk embeddings once and keep them in memory.

    The file is re-read only when its modification time or size
    changes, so re-running the embedding step is picked up without
    restarting the API.
    """
    global _store

    stat = os.stat(INPUT_FILE)
    signature = (stat.st_mtime_ns, stat.st_size)

    if _store is not None and _store.signature == signature:
        return _store

    with _store_lock:
        if _store is None or _store.signature != signature:
            with timed_stage("chunk_store_load"):
                chunks = load_chunks()
                embeddings = np.asarray(
                    [chunk["embedding"] for chunk in chunks],
                    dtype=np.float64,
                )
                _store = ChunkStore(signature, chunks, embeddings)

    return _store


class QueryEmbeddingCache:
    """
    Small thread-safe LRU cache for query embeddings.

    Keys are (model name, exact query text). An embedding depends only
    on those two inputs, so cached values never leak information
    between customers; entries still expire after `ttl_seconds`.
    """

    def __init__(self, max_size: int = 256, ttl_seconds: float = 3600):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._items: OrderedDict[tuple[str, str], tuple[float, np.ndarray]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: tuple[str, str]) -> np.ndarray | None:
        with self._lock:
            item = self._items.get(key)

            if item is None:
                return None

            stored_at, value = item

            if time.monotonic() - stored_at > self.ttl_seconds:
                del self._items[key]
                return None

            self._items.move_to_end(key)
            return value

    def put(self, key: tuple[str, str], value: np.ndarray) -> None:
        value.setflags(write=False)

        with self._lock:
            self._items[key] = (time.monotonic(), value)
            self._items.move_to_end(key)

            while len(self._items) > self.max_size:
                self._items.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def __len__(self) -> int:
        return len(self._items)


query_embedding_cache = QueryEmbeddingCache()


def embed_query(query: str) -> np.ndarray:
    """Return the (1, dim) embedding for a query, using the cache."""
    key = (MODEL_NAME, query)
    cached = query_embedding_cache.get(key)

    if cached is not None:
        return cached

    embedding = get_embedding_model().encode([query])
    query_embedding_cache.put(key, embedding)

    return embedding


def warm_up() -> None:
    """Load the model and embeddings and run one encode, ahead of traffic."""
    get_embedding_model()
    get_chunk_store()
    # The first encode call is noticeably slower than later ones.
    get_embedding_model().encode(["warm-up"])


# ============================================================
# SEARCH
# ============================================================

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
    store = get_chunk_store()

    # Step 1: Apply metadata filters when provided.
    indexes = [
        index
        for index, chunk in enumerate(store.chunks)
        if (not customer_id or chunk.get("customer_id") == customer_id)
        and (not loan_id or chunk.get("loan_id") == loan_id)
        and (not document_type or chunk.get("document_type") == document_type)
    ]
    chunks = [store.chunks[index] for index in indexes]

    print(f"Candidate chunks after filtering: {len(chunks)}")

    if not chunks:
        return []

    # Step 2: Embed the user's question.
    with timed_stage("query_embedding"):
        query_embedding = embed_query(query)

    with timed_stage("vector_search"):
        # Step 3: Compare the question against stored chunk embeddings.
        similarities = cosine_similarity(
            query_embedding,
            store.embeddings[indexes],
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


def search_with_analysis(
    query: str,
    top_k: int = 5,
    analysis: QueryAnalysis | None = None,
):
    """
    Analyze a natural-language question, infer metadata filters,
    and run semantic search automatically.

    Pass `analysis` to reuse one already computed for this question.
    """
    if analysis is None:
        with timed_stage("query_analysis"):
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