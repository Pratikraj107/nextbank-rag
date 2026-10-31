"""Document Explorer API: listing, filters, detail, chunks and failure modes."""

import json
import os

import pytest
from fastapi.testclient import TestClient

import src.api.main as api
from src.api.documents import get_document_library
from src.documents.library import DocumentLibrary, stable_document_id

PAYSLIP = {
    "document_id": "uuid-payslip", "loan_id": "NB-LOAN-2101", "customer_id": "NB-CUST-3001",
    "document_type": "payslip", "source": "data/raw/NB-LOAN-2101/pdf/03_payslip.pdf",
    "source_type": "pdf", "content": "Gross monthly salary: EUR 6,000.00", "language": None,
    "metadata": {"gross_monthly_salary": 6000.0},
}
OFFER = {
    "document_id": "uuid-offer", "loan_id": "NB-LOAN-2102", "customer_id": "NB-CUST-3002",
    "document_type": "loan_offer", "source": "data/raw/NB-LOAN-2102/pdf/08_loan_offer.pdf",
    "source_type": "pdf", "content": "Principal: EUR 30,000", "language": None, "metadata": {},
}
# CSV rows share one source file; one has no loan ID.
CSV_ROW_2 = {
    "document_id": "uuid-csv-2", "loan_id": None, "customer_id": "NB-CUST-3001",
    "document_type": "csv_record", "source": "data\\raw\\enterprise_csv\\customers.csv",
    "source_type": "csv", "content": "customer_id: NB-CUST-3001", "language": None,
    "metadata": {"row_number": 2, "record": {"customer_id": "NB-CUST-3001"}},
}
CSV_ROW_3 = dict(CSV_ROW_2, document_id="uuid-csv-3", customer_id="NB-CUST-3002",
                 metadata={"row_number": 3, "record": {"customer_id": "NB-CUST-3002"}})
# Only the fields every record is guaranteed to have.
BARE = {"document_id": "uuid-bare", "source": "data/raw/misc/notes.txt", "content": ""}

CHUNKS = [
    {"chunk_id": "c-2", "document_id": "uuid-payslip", "chunk_index": 2, "content": "third"},
    {"chunk_id": "c-0", "document_id": "uuid-payslip", "chunk_index": 0, "content": "first",
     "document_type": "payslip", "customer_id": "NB-CUST-3001", "loan_id": "NB-LOAN-2101"},
    {"chunk_id": "c-1", "document_id": "uuid-payslip", "chunk_index": 1, "content": "second"},
    {"chunk_id": "c-offer", "document_id": "uuid-offer", "chunk_index": 0, "content": "Principal"},
]

ALL_DOCUMENTS = [PAYSLIP, OFFER, CSV_ROW_2, CSV_ROW_3, BARE]


def write_jsonl(path, records):
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


@pytest.fixture
def data_dir(tmp_path):
    write_jsonl(tmp_path / "documents.jsonl", ALL_DOCUMENTS)
    write_jsonl(tmp_path / "chunks.jsonl", CHUNKS)
    return tmp_path


@pytest.fixture
def client(data_dir):
    library = DocumentLibrary(data_dir / "documents.jsonl", data_dir / "chunks.jsonl")
    api.app.dependency_overrides[get_document_library] = lambda: library
    # Not used as a context manager, so the startup warm-up does not run.
    yield TestClient(api.app)
    api.app.dependency_overrides.clear()


def doc_id(record):
    return stable_document_id(record["source"], record.get("metadata", {}).get("row_number"))


# ------------------------------------------------------------
# Listing, search, filters, pagination
# ------------------------------------------------------------

def test_lists_all_documents_in_stable_order(client):
    body = client.get("/api/documents").json()

    assert body["total"] == 5
    sources = [item["source"] for item in body["items"]]
    assert sources == sorted(sources)
    # CSV rows from one file keep their row order.
    csv_rows = [item["row_number"] for item in body["items"] if item["source_type"] == "csv"]
    assert csv_rows == [2, 3]


def test_pagination_and_total_count(client):
    first = client.get("/api/documents", params={"page_size": 2, "page": 1}).json()
    third = client.get("/api/documents", params={"page_size": 2, "page": 3}).json()
    beyond = client.get("/api/documents", params={"page_size": 2, "page": 9}).json()

    assert first["total"] == 5 and first["total_pages"] == 3 and len(first["items"]) == 2
    assert len(third["items"]) == 1
    assert beyond["items"] == [] and beyond["total"] == 5
    all_ids = [i["id"] for p in (1, 2, 3)
               for i in client.get("/api/documents", params={"page_size": 2, "page": p}).json()["items"]]
    assert len(set(all_ids)) == 5


def test_search_matches_filename_and_path_case_insensitively(client):
    assert [i["filename"] for i in client.get("/api/documents", params={"q": "PAYSLIP"}).json()["items"]] == ["03_payslip.pdf"]
    assert client.get("/api/documents", params={"q": "enterprise_csv"}).json()["total"] == 2
    assert client.get("/api/documents", params={"q": "no-such-file"}).json()["total"] == 0


@pytest.mark.parametrize(
    "params, expected_total",
    [
        ({"document_type": "payslip"}, 1),
        ({"customer_id": "NB-CUST-3001"}, 2),
        ({"loan_id": "NB-LOAN-2102"}, 1),
        ({"customer_id": "NB-CUST-3001", "loan_id": "NB-LOAN-2101"}, 1),
        ({"document_type": "payslip", "loan_id": "NB-LOAN-2102"}, 0),
        ({"document_type": "  "}, 5),  # blank filters are ignored
    ],
)
def test_filters(client, params, expected_total):
    assert client.get("/api/documents", params=params).json()["total"] == expected_total


def test_facets_cover_the_whole_library(client):
    body = client.get("/api/documents", params={"document_type": "payslip"}).json()
    facets = body["facets"]

    assert body["total"] == 1 and body["library_total"] == 5

    assert {f["value"] for f in facets["document_types"]} == {"payslip", "loan_offer", "csv_record"}
    assert {f["value"]: f["count"] for f in facets["customer_ids"]} == {"NB-CUST-3001": 2, "NB-CUST-3002": 2}
    assert {f["value"] for f in facets["loan_ids"]} == {"NB-LOAN-2101", "NB-LOAN-2102"}


def test_missing_metadata_is_null_not_invented(client):
    [bare] = client.get("/api/documents", params={"q": "notes.txt"}).json()["items"]

    assert bare["document_type"] is None
    assert bare["customer_id"] is None and bare["loan_id"] is None
    assert bare["source_type"] is None and bare["row_number"] is None
    assert bare["chunk_count"] == 0


@pytest.mark.parametrize(
    "params",
    [{"page": 0}, {"page_size": 0}, {"page_size": 101}, {"q": "x" * 201}],
)
def test_invalid_query_parameters_are_rejected(client, params):
    assert client.get("/api/documents", params=params).status_code == 422

# ------------------------------------------------------------
# Detail and chunks
# ------------------------------------------------------------

def test_document_detail(client):
    body = client.get(f"/api/documents/{doc_id(PAYSLIP)}").json()

    assert body["filename"] == "03_payslip.pdf"
    assert body["content"] == PAYSLIP["content"]
    assert body["metadata"] == {"gross_monthly_salary": 6000.0}
    assert body["chunk_count"] == 3


def test_csv_rows_get_distinct_ids_and_posix_sources(client):
    first = client.get(f"/api/documents/{doc_id(CSV_ROW_2)}").json()
    second = client.get(f"/api/documents/{doc_id(CSV_ROW_3)}").json()

    assert first["id"] != second["id"]
    assert first["source"] == "data/raw/enterprise_csv/customers.csv"
    assert first["row_number"] == 2 and second["row_number"] == 3


def test_ids_are_stable_across_reingestion(data_dir):
    first = DocumentLibrary(data_dir / "documents.jsonl", data_dir / "chunks.jsonl")
    ids_before = [d.id for d in first.all()]

    # Re-ingestion assigns new random document_ids.
    renamed = [dict(r, document_id=r["document_id"] + "-new") for r in ALL_DOCUMENTS]
    write_jsonl(data_dir / "documents.jsonl", renamed)
    write_jsonl(data_dir / "chunks.jsonl", [dict(c, document_id=c["document_id"] + "-new") for c in CHUNKS])
    second = DocumentLibrary(data_dir / "documents.jsonl", data_dir / "chunks.jsonl")

    assert [d.id for d in second.all()] == ids_before


def test_chunks_are_ordered_by_index(client):
    body = client.get(f"/api/documents/{doc_id(PAYSLIP)}/chunks").json()

    assert body["total"] == 3
    assert [c["chunk_index"] for c in body["chunks"]] == [0, 1, 2]
    assert [c["content"] for c in body["chunks"]] == ["first", "second", "third"]
    assert body["chunks"][0]["loan_id"] == "NB-LOAN-2101"
    assert body["chunks"][1]["loan_id"] is None  # not invented from the document


def test_document_without_chunks_returns_empty_list(client):
    body = client.get(f"/api/documents/{doc_id(BARE)}/chunks").json()

    assert body == {"document_id": doc_id(BARE), "total": 0, "chunks": []}


@pytest.mark.parametrize("suffix", ["", "/chunks"])
@pytest.mark.parametrize(
    "document_id",
    [
        "doc_0000000000000000",          # well-formed but unknown
        "uuid-payslip",                  # internal ingestion IDs are not accepted
        "DOC_8535BB5D871FAEA1",
        "doc_123",
        "..%2F..%2Fetc%2Fpasswd",
        "%2Fetc%2Fpasswd",
        "data%2Fprocessed%2Fdocuments.jsonl",
    ],
)
def test_unknown_or_path_like_ids_return_404(client, document_id, suffix):
    response = client.get(f"/api/documents/{document_id}{suffix}")

    assert response.status_code == 404
    assert "root:" not in response.text


def test_library_never_opens_requested_ids(data_dir, monkeypatch):
    library = DocumentLibrary(data_dir / "documents.jsonl", data_dir / "chunks.jsonl")
    library.all()
    opened = []
    real_open = open

    def spy(path, *args, **kwargs):
        opened.append(str(path))
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", spy)

    assert library.get("../../etc/passwd") is None
    assert library.get(doc_id(PAYSLIP)) is not None
    assert opened == []

# ------------------------------------------------------------
# Caching and data problems
# ------------------------------------------------------------

def test_library_is_cached_and_reloads_when_files_change(data_dir):
    library = DocumentLibrary(data_dir / "documents.jsonl", data_dir / "chunks.jsonl")
    first = library.all()

    assert library.all() is first  # no re-read without changes

    write_jsonl(data_dir / "documents.jsonl", [PAYSLIP])
    write_jsonl(data_dir / "chunks.jsonl", CHUNKS[:3])
    stat = os.stat(data_dir / "documents.jsonl")
    os.utime(data_dir / "documents.jsonl", ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))

    assert len(library.all()) == 1


def failing_client(data_dir):
    library = DocumentLibrary(data_dir / "documents.jsonl", data_dir / "chunks.jsonl")
    api.app.dependency_overrides[get_document_library] = lambda: library
    return TestClient(api.app)


@pytest.mark.parametrize(
    "setup, message",
    [
        (lambda d: (d / "documents.jsonl").unlink(), "Documents file not found"),
        (lambda d: (d / "chunks.jsonl").unlink(), "Chunks file not found"),
        (lambda d: (d / "documents.jsonl").write_text('{"source": "x"\n'), "invalid JSON on line 1"),
        (lambda d: write_jsonl(d / "documents.jsonl", [{"source": "x", "content": ""}]), "missing ['document_id']"),
        (lambda d: write_jsonl(d / "documents.jsonl", [PAYSLIP]), "out of date"),
        (lambda d: write_jsonl(d / "documents.jsonl", [PAYSLIP, dict(PAYSLIP, document_id="dup")]), "cannot assign stable IDs"),
    ],
)
def test_bad_data_fails_clearly_with_503(data_dir, setup, message):
    setup(data_dir)
    client = failing_client(data_dir)
    try:
        for path in ("/api/documents", f"/api/documents/{doc_id(PAYSLIP)}"):
            response = client.get(path)
            assert response.status_code == 503
            assert message in response.json()["detail"]
            assert str(data_dir) not in response.json()["detail"]  # no filesystem paths
    finally:
        api.app.dependency_overrides.clear()


def test_real_processed_data_loads():
    library = DocumentLibrary()
    documents = library.all()

    assert len(documents) == len({d.id for d in documents})
    assert all(d.chunks for d in documents)
    assert sum(len(d.chunks) for d in documents) == sum(
        1 for line in open(library.chunks_path, encoding="utf-8") if line.strip()
    )
