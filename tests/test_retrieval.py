"""Model lifecycle, query-embedding cache, and retrieval equivalence."""

import json

import numpy as np
import pytest

import src.embeddings.semantic_search as semantic_search
from src.embeddings.semantic_search import QueryEmbeddingCache
from src.retrieval.query_analyzer import QueryAnalyzer


# ------------------------------------------------------------
# Query embedding cache
# ------------------------------------------------------------

def test_cache_evicts_least_recently_used():
    cache = QueryEmbeddingCache(max_size=2)
    cache.put(("m", "a"), np.zeros((1, 2)))
    cache.put(("m", "b"), np.zeros((1, 2)))
    cache.get(("m", "a"))
    cache.put(("m", "c"), np.zeros((1, 2)))

    assert cache.get(("m", "b")) is None
    assert cache.get(("m", "a")) is not None
    assert len(cache) == 2


def test_cache_entries_expire(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(semantic_search.time, "monotonic", lambda: now[0])
    cache = QueryEmbeddingCache(ttl_seconds=10)
    cache.put(("m", "a"), np.zeros((1, 2)))

    now[0] += 11

    assert cache.get(("m", "a")) is None


def test_cached_embeddings_are_read_only():
    cache = QueryEmbeddingCache()
    cache.put(("m", "a"), np.zeros((1, 2)))

    with pytest.raises(ValueError):
        cache.get(("m", "a"))[0, 0] = 1.0


# ------------------------------------------------------------
# Model is loaded once; repeated queries are not re-encoded
# ------------------------------------------------------------

class CountingModel:
    instances = 0

    def __init__(self, name):
        CountingModel.instances += 1
        self.encode_calls = 0

    def encode(self, texts):
        self.encode_calls += 1
        return np.ones((len(texts), 768))


def test_model_loaded_once_and_query_embedding_reused(monkeypatch):
    CountingModel.instances = 0
    monkeypatch.setattr(semantic_search, "SentenceTransformer", CountingModel)
    monkeypatch.setattr(semantic_search, "_model", None)
    monkeypatch.setattr(semantic_search, "query_embedding_cache", QueryEmbeddingCache())

    for _ in range(3):
        semantic_search.search("annual salary", top_k=5, customer_id="NB-CUST-3001")

    assert CountingModel.instances == 1
    assert semantic_search.get_embedding_model().encode_calls == 1


# ------------------------------------------------------------
# Optimised search returns exactly what the original code returned
# ------------------------------------------------------------

def reference_search(model, query, top_k, customer_id=None, loan_id=None, document_type=None):
    """The pre-optimisation algorithm: reload file, filter, rank."""
    from sklearn.metrics.pairwise import cosine_similarity

    with open(semantic_search.INPUT_FILE, encoding="utf-8") as file:
        chunks = [json.loads(line) for line in file if line.strip()]

    chunks = [
        chunk for chunk in chunks
        if (not customer_id or chunk.get("customer_id") == customer_id)
        and (not loan_id or chunk.get("loan_id") == loan_id)
        and (not document_type or chunk.get("document_type") == document_type)
    ]
    similarities = cosine_similarity(model.encode([query]), [c["embedding"] for c in chunks])[0]
    ranked = sorted(zip(chunks, similarities), key=lambda pair: pair[1], reverse=True)
    return [(chunk["chunk_id"], float(score)) for chunk, score in ranked[:top_k]]


@pytest.mark.parametrize(
    "query, filters",
    [
        ("What is Lotte van Dijk's annual salary?", {"customer_id": "NB-CUST-3001", "document_type": "employment_agreement"}),
        ("What is Thomas de Boer's monthly gross salary?", {"customer_id": "NB-CUST-3002", "document_type": "payslip"}),
        ("What is Lotte van Dijk's favorite color?", {"customer_id": "NB-CUST-3001"}),
        ("loan term", {"loan_id": "NB-LOAN-2101"}),
        ("SEPA mandate creditor identifier", {}),
    ],
)
def test_search_matches_reference_and_keeps_metadata(query, filters):
    model = semantic_search.get_embedding_model()

    results = semantic_search.search(query, top_k=8, **filters)
    expected = reference_search(model, query, 8, **filters)

    assert [r["chunk"]["chunk_id"] for r in results] == [chunk_id for chunk_id, _ in expected]
    assert [r["score"] for r in results] == pytest.approx([score for _, score in expected], abs=1e-6)

    for result in results:
        chunk = result["chunk"]
        for field in ("source", "document_type", "customer_id", "loan_id", "chunk_index", "content"):
            assert field in chunk


# ------------------------------------------------------------
# Verified identifiers from the enterprise CSVs
# ------------------------------------------------------------

def test_analyzer_knows_all_csv_customers_and_loans():
    analysis = QueryAnalyzer().analyze("Is Nina Jansen the borrower on NB-LOAN-2101?")

    assert analysis.customer_id == "NB-CUST-3003"
    assert analysis.entity_conflict is not None


def test_analyzer_accepts_matching_customer_and_loan():
    analysis = QueryAnalyzer().analyze("What is Nina Jansen's loan term on NB-LOAN-2103?")

    assert analysis.customer_id == "NB-CUST-3003"
    assert analysis.loan_id == "NB-LOAN-2103"
    assert analysis.entity_conflict is None
