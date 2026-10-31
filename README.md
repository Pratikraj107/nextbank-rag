# NexaBank AI — Loan Document Intelligence

A local prototype that answers questions about synthetic NexaBank loan documents
with cited, validated answers, and lets reviewers browse the ingested documents.

- **Backend:** Python, FastAPI, LangGraph agent, `BAAI/bge-base-en-v1.5` embeddings, `gpt-5-mini`
- **Frontend:** React + TypeScript + Vite + Tailwind (`frontend/`)
- **Data:** synthetic documents in `data/raw/`, processed into `data/processed/`

> All data is synthetic. There is **no authentication or authorisation**; run it
> only on your own machine.

## Running locally

Prerequisites: [uv](https://docs.astral.sh/uv/), Node.js 20+, and `OPENAI_API_KEY`
for the chat assistant. The Document Explorer does not need the key.

```bash
# Terminal 1 — backend (project root)
export OPENAI_API_KEY=...            # needed for the chat assistant
uv run uvicorn src.api.main:app --reload

# Terminal 2 — frontend
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. The API runs on <http://127.0.0.1:8000>. Set
`VITE_API_BASE_URL` in `frontend/.env` to use a different address (see
`frontend/.env.example`).

## Rebuilding the processed data

```bash
uv run python -m src.main                     # raw files → data/processed/documents.jsonl
uv run python -m src.chunking.pipeline        # documents → data/processed/chunks.jsonl
uv run python -m src.embeddings.embed_chunks  # chunks → data/processed/chunk_embeddings.jsonl
```

Run all three in order: each step depends on the previous one's output.

## Document Explorer

Open **Document Explorer** in the sidebar (or go to `/#/documents`) to:

- browse all ingested documents, 20 per page, with the total library size shown;
- search by filename or source path, and filter by document type, customer ID and loan ID;
- open a document to see its metadata, extracted text, chunks (with copy buttons) and the
  fields extracted during ingestion;
- use **Ask about this document** to open the chat with an editable question about it. The
  assistant still searches all documents; the chat API has no document-scoping option.

The selected document is kept in the URL (`/#/documents?doc=doc_…`), so a refresh or a shared
link reopens it. Missing metadata is shown as "Not set"; nothing is filled in or estimated.

### Endpoints

All three are read-only and never call the agent, the embedding model or the LLM.

| Method and path | Description |
|---|---|
| `GET /api/documents` | Paginated document summaries |
| `GET /api/documents/{document_id}` | Metadata, extracted text and extracted fields |
| `GET /api/documents/{document_id}/chunks` | Chunks ordered by `chunk_index` (empty list if none) |

Query parameters for `GET /api/documents`:

| Parameter | Default | Notes |
|---|---|---|
| `q` | — | Case-insensitive substring of the filename or source path (max 200 chars) |
| `document_type` | — | Exact match, e.g. `payslip` |
| `customer_id` | — | Exact match, e.g. `NB-CUST-3001` |
| `loan_id` | — | Exact match, e.g. `NB-LOAN-2101` |
| `page` | `1` | ≥ 1 |
| `page_size` | `25` | 1–100 |

The response includes `total` (matching documents), `library_total` (all documents),
`total_pages`, and `facets`: the distinct document types, customer IDs and loan IDs across
the whole library, with counts, for filter menus.

```bash
curl "http://127.0.0.1:8000/api/documents?loan_id=NB-LOAN-2101&document_type=payslip"
curl "http://127.0.0.1:8000/api/documents?q=transactions&page_size=5&page=2"
curl "http://127.0.0.1:8000/api/documents/doc_8535bb5d871faea1"
curl "http://127.0.0.1:8000/api/documents/doc_8535bb5d871faea1/chunks"
```

Errors: `404` for unknown or malformed document IDs, `422` for invalid query parameters, and
`503` with the reason when the processed data is missing, malformed or inconsistent (for
example, a chunk file left over from an earlier ingestion run).

### Document IDs

`document_id` values in `documents.jsonl` are random and change on every ingestion run, so
they are not used in URLs. Each document instead gets a stable ID:

```
doc_ + first 16 hex characters of sha256("<source path>#row=<CSV row number or empty>")
```

Source paths are normalised to forward slashes. CSV files hold one document per row, so the
row number keeps those IDs distinct. IDs survive re-ingestion as long as source paths do not
change. The API accepts only IDs of exactly this shape and never reads files based on the
request, so no path can be requested through it.

### Loading, caching and refreshing

The library is read from `data/processed/documents.jsonl` and `data/processed/chunks.jsonl`
only. It is parsed once and kept in memory, and loaded at API startup so data problems appear
in the server log immediately. Each request checks the two files' modification times and
sizes; after you re-run ingestion or chunking, the next request reloads them automatically.
Restarting the API also reloads them.

## Uploading documents

In Document Explorer, **Upload document** opens a panel where you drop or choose a file,
pick the customer (and optionally one of that customer's loans), and start processing.
Progress is shown step by step; the status stays visible in the header if you close the
panel. When the job is **ready**, the list refreshes and **Open document** shows its text
and chunks. The document can then be retrieved by the chat assistant like any other.

- **Formats:** `.pdf`, `.docx`, `.html`/`.htm`, `.eml`. The content is checked as well as the
  extension (PDF header, Word package contents, HTML markup, email headers). CSV is not
  accepted: the existing CSVs are multi-customer system exports, not one customer's document.
- **Size limit:** 10 MB by default (`NEXABANK_MAX_UPLOAD_MB`).
- **Customer and loan:** must exist in `data/raw/enterprise_csv/`, and the loan must belong to
  the customer. If the document's own text names a different customer or loan, processing fails.
- **Duplicates:** the same file (SHA-256) for the same customer and loan returns the existing
  job instead of processing it again.

### Endpoints

| Method and path | Description |
|---|---|
| `GET /api/documents/upload-options` | Accepted formats, size limit, customers and loans |
| `POST /api/documents/upload` | Multipart form: `file`, `customer_id`, optional `loan_id`. Returns `202` with the job |
| `GET /api/jobs` | Jobs, newest first. Filters: `status`, `customer_id`, `document_type`; `page`, `page_size` (1–100). Includes `facets` for filter menus |
| `GET /api/jobs/{job_id}` | One job with its stages |
| `POST /api/jobs/{job_id}/retry` | Re-run a failed job if `retryable` is true (otherwise `409`) |

```bash
curl -F file=@bonus_letter.docx -F customer_id=NB-CUST-3001 -F loan_id=NB-LOAN-2101 \
     http://127.0.0.1:8000/api/documents/upload
curl http://127.0.0.1:8000/api/jobs/<job_id>
```

Rejections: `415` unsupported or mismatched file type, `413` too large, `400` empty file,
`422` unknown customer or loan, or a loan that belongs to another customer.

### Activity Center

Sidebar → **Activity** (or `/#/activity`) lists every upload job with its customer, upload
time, duration and status, filterable by status, customer and document type. Selecting a job
(`/#/activity?job=<id>`) shows each processing stage with its status, duration and any error,
the job's warnings, a **Retry** button when the failure can be retried, and **Open in
Document Explorer** once it is ready. The list refreshes itself while any job on screen is
still queued or processing.

**Job lifecycle.** A job is created when an upload passes validation, so rejected uploads
(wrong type, too large, unknown customer, mismatched loan) return an error and are not listed.

```
uploaded ──▶ processing ──▶ ready
                 │
                 └────────▶ failed ──(retry, if retryable)──▶ uploaded
```

| Stage | What happens | Typical failure | Retryable |
|---|---|---|---|
| `validation` | File type, content, size, customer and loan checks (during the upload request) | rejected upload, no job created | — |
| `parsing` | Text extraction with the existing parser | unreadable or empty file | no |
| `normalization` | Classification, metadata extraction, identifier consistency | document names another customer or loan | no |
| `chunking` | Existing `RecursiveChunker` | no searchable text | no |
| `embedding` | Embeddings for the new chunks (model loaded once per process) | model error | yes |
| `indexing` | Write records, then confirm the library, semantic search and exact search see them | write or verification error | yes |

Each stage records `status` (`pending`, `running`, `completed`, `failed`), start and finish
times, `duration_ms` and a safe error message. A job's `duration_ms` covers its latest attempt,
from being queued to finishing.

**Staying consistent with the index.** When jobs are listed or read (and at startup), a
`ready` job whose document is no longer in the processed data — for example after the batch
pipeline rebuilt `data/processed/` — is marked `failed` at `indexing` and `retryable`, and
Retry re-indexes it from the stored original.

### How ingestion works

Each job runs on a single background thread inside the API process and reuses the existing
code: `IngestionPipeline` (parsers, classifier, metadata extraction, validation), the same
`RecursiveChunker` settings as the batch pipeline, and the embedding model already loaded by
the API. Only the new document's chunks are embedded.

Records are written to `documents.jsonl`, `chunks.jsonl` and `chunk_embeddings.jsonl` by
`ProcessedStore`: each file is rewritten to a temporary file and swapped in atomically, in an
order that never leaves a chunk pointing at a missing document. Writing a document again
replaces its earlier records, so retries never create duplicates. Semantic search, exact search
and the document library all reload these files when they change, so no restart is needed.

A job is marked **ready** only after the document library, semantic search and exact search
have all been checked to contain the new document. Any failure removes whatever was written,
and the job is marked **failed** with a reason that is safe to display.

### Storage and limitations

- Originals are stored under `data/uploads/<job_id>/<sanitised filename>`, with the job record
  in `job.json` beside it (`NEXABANK_UPLOAD_DIR` to change). `data/uploads/` is git-ignored.
- The job queue is in memory. If the API stops while a job is queued or running, that job is
  marked failed (at the stage that was running) on the next start and can be retried. Job
  records and originals persist.
- Re-running the batch ingestion commands rebuilds `data/processed/` from `data/raw/` only, which
  **removes uploaded documents** from search. The Activity Center then shows those jobs as
  failed at indexing; use Retry on each to re-index them.
- Jobs recorded before stage tracking was added are migrated when loaded: their stages are
  shown as completed (or failed) without timings, because none were recorded.
- Every write rewrites the JSONL files, which is fine for this prototype's size but not for large
  libraries. One worker process only: running several API workers would need a shared lock.
- Scanned PDFs without a text layer cannot be read (there is no OCR).

### Moving to production infrastructure

The pieces are separated so each can be replaced on its own:

- **Database (PostgreSQL + pgvector):** `ProcessedStore.upsert_source` becomes one transaction
  that deletes and inserts a document's rows; the readers (`DocumentLibrary`, `semantic_search`,
  `exact_search`) query tables instead of reloading JSONL. Job records become a `jobs` table.
- **Object storage (e.g. S3):** replace the file writes in `IngestionService.submit` and the
  read in `_parse` with object puts and gets keyed by `job_id`.
- **Durable worker (e.g. a task queue):** `IngestionService._run` is already a self-contained
  job function; enqueue it instead of using the in-process thread pool, and the restart
  limitation goes away.

## Tests and evaluation

```bash
uv run pytest                                                       # offline tests, no API key needed
uv run python scripts/evaluate_agent.py --api-url http://127.0.0.1:8000   # live evaluation of the agent
```

See `docs/latency-optimization.md` for performance work and `reports/evaluations/` for
evaluation results.
