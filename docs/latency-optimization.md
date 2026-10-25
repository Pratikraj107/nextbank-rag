# Latency Optimization — NexaBank Loan Intelligence Assistant

This document explains how the response time of the NexaBank assistant was
measured, what was changed to reduce it, how correctness was protected, and
what remains slow. Key terms are defined in the [Glossary](#glossary) at the end.

- **Branch:** `perf/latency`
- **Scope:** Python backend only (`src/`). The React frontend and the API
  contract it relies on are unchanged.

---

## 1. Summary

| | Before | After | Change |
|---|---|---|---|
| Median response time (questions that call the LLM) | 17.4 s | 11.5 s | **−34%** |
| p95 response time | 24.9 s | 17.8 s | **−28%** |
| First request after a server restart | 23.0 s | 7.8 s | **−66%** |
| Regression checks passed | 18 / 18 | 18 / 18 | unchanged |

Two changes account for almost all of the improvement:

1. The embedding model is loaded **once** instead of on every request (saves ~4.6 s per request).
2. The answer-generating LLM call uses **lower reasoning effort** (generation median 4.1 s → 1.9 s),
   while the evidence validator that checks the answer is left unchanged.

The remaining time is dominated by the evidence-validation LLM call
(median ~8.8 s), which was intentionally not weakened. See
[Section 7](#7-remaining-bottleneck).

---

## 2. How the system answers a question

A question sent to `POST /api/chat` goes through a LangGraph workflow
(`src/agents/rag_agent.py`):

```
route_query ─┬─ identifier conflict  → refuse immediately (no retrieval, no LLM)
             ├─ exact phrase search   → literal text search over documents
             └─ normal question       → answer:
                                          query analysis → filters
                                          embed question → vector search
                                          assemble context → LLM writes answer   (LLM call 1)
                                        → basic validation (citation labels)
                                        → evidence validation                     (LLM call 2)
                                        → finish | retry (max 2 attempts) | abstain
```

A normal question therefore costs **two LLM calls**, plus retrieval. A retry
repeats both.

---

## 3. How latency was measured

Nothing was optimized until it had been measured.

### 3.1 Instrumentation

A small timing module, `src/observability/timing.py`, was added. It records
how long each stage takes using Python's `time.perf_counter()`:

- Each request gets a **request ID** (also returned in the `X-Request-ID` response header).
- Each stage is logged as one JSON line with the request ID, stage name,
  attempt number, duration and status.
- If a stage raises an exception, its duration is **still recorded**, along
  with the exception type, so failed requests show where time went.
- Logs contain stage names, timings and token counts only — never question
  text, document content, customer records or API keys.

Stages measured: `route_query`, `query_analysis`, `exact_search`,
`embedding_model_load`, `chunk_store_load`, `query_embedding`,
`vector_search`, `context_assembly`, `answer_generation`, `basic_validation`,
`evidence_validation`, `retry_evidence_check`, per-attempt totals, and the
request total.

In development the API response also includes two optional fields,
`timings_ms` and `token_usage`. They are hidden when
`NEXABANK_ENV=production`. The frontend ignores them.

### 3.2 Benchmark

`scripts/latency_benchmark.py` sends the same six questions to the running API
several times, checks every answer, and reports the median and p95 per stage.

| Case | Question | Expected behaviour |
|---|---|---|
| `salary_lotte` | Lotte van Dijk's annual gross salary | EUR 72,000, with valid citations |
| `salary_thomas` | Thomas de Boer's monthly gross salary | EUR 6,750, with valid citations |
| `tenure_claim` | Does the agreement confirm ≥ 10 years at the employer? | Must not affirm it; the start date is 3 May 2021 |
| `favorite_color` | Lotte van Dijk's favorite color | Says the documents do not state it |
| `conflict` | Thomas de Boer + loan NB-LOAN-2101 | Detects the mismatch; no answer generated |
| `net_salary_citations` | Lotte van Dijk's monthly net salary | EUR 4,300; citations map to NB-LOAN-2101 sources |

**Warm** runs (server already running): 3 rounds × 6 questions. Statistics
cover the 15 requests that call the LLM. The conflict case is reported
separately.

**Cold** runs: the server is restarted, and the first request is timed.

Raw results are stored in `data/benchmarks/`:

| File | What it contains |
|---|---|
| `latency_before.json`, `latency_before-cold.json` | Baseline, original code with timing added |
| `latency_after.json`, `latency_after-tokens.json`, `latency_after-cold.json` | After the infrastructure changes |
| `latency_after-answer-low.json` | Final configuration |

---

## 4. What the measurements showed

### 4.1 Baseline (median / p95, 15 requests)

| Stage | Median | p95 | Share of median total |
|---|---|---|---|
| Embedding model load | 4,640 ms | 4,897 ms | 27% |
| Read embeddings file | 16 ms | 25 ms | <1% |
| Query analysis | <0.1 ms | <0.1 ms | ~0% |
| Query embedding | 15 ms | 21 ms | <1% |
| Vector search | 0.4 ms | 1.2 ms | ~0% |
| Answer generation (LLM) | 3,943 ms | 7,406 ms | 23% |
| Basic validation | 0.1 ms | 0.1 ms | ~0% |
| Evidence validation (LLM) | 8,158 ms | 15,500 ms | 47% |
| **Total** | **17,402 ms** | **24,861 ms** | |

The conflict question took about 6 ms, because it never reaches retrieval or
the LLM. No question needed a retry.

### 4.2 Findings

1. **The embedding model was reloaded on every search.** `search()` called
   `SentenceTransformer(MODEL_NAME)` each time, which took about 4.6 s. It was
   the only significant non-LLM cost. A retry would have paid it twice.
2. **The 2 MB embeddings file was re-read and re-parsed on every search.**
   This was small (about 16 ms) but needless.
3. **The question was analysed twice**, once by the router and again by
   retrieval. This was negligible in time, but it was duplicated work.
4. **A new OpenAI client was created for every answer**, so connections were
   never reused.
5. **The LLM time is mostly reasoning.** Token counts per call:

   | Call | Input tokens | Output tokens (median / max) | of which reasoning |
   |---|---|---|---|
   | Answer generation | ~390 | ~285 / 543 | ~190 |
   | Evidence validation | ~750 | ~840 / 1,415 | ~700 (84%) |

   The prompts are already small, so shortening them would save little.
   The time is spent generating hidden reasoning tokens.
6. **Some retries could never succeed.** For example, if retrieval found
   nothing, a retry with the same filters finds nothing again. If the
   validator itself crashed, generating a new answer does not fix the
   validator.
7. **There is nothing to parallelise.** Validation needs the finished answer,
   and a request uses either exact search or semantic search, never both.
   Query analysis is already rule-based and has no LLM call.

---

## 5. Changes made

Each change is small and keeps the existing architecture, including LangGraph.

### 5.1 Load the embedding model once

**Files:** `src/embeddings/semantic_search.py`, `src/api/main.py`

- **What:** `get_embedding_model()` loads `BAAI/bge-base-en-v1.5` the first
  time it is needed and returns the same object afterwards. A lock prevents
  two simultaneous requests from loading it twice.
- **Startup warm-up:** the API's `lifespan` handler calls `warm_up()` before
  serving traffic. It loads the model and the embeddings, and runs one
  throw-away encode, because the first encode is slower (~700 ms).
- **Effect:** removes ~4.6 s from every request. The server now takes about
  6 s to start instead of ~1.3 s, because that work moved from the user's
  first request to startup.

### 5.2 Keep chunk embeddings in memory

**File:** `src/embeddings/semantic_search.py`

- **What:** `get_chunk_store()` reads `data/processed/chunk_embeddings.jsonl`
  once and stores the embeddings as a NumPy matrix.
- **Freshness:** it checks the file's modification time and size on each call.
  If you re-run the embedding step, the new file is picked up automatically,
  without restarting the API.
- **Correctness:** ranking uses the same cosine-similarity calculation as
  before. A test confirms that the new search returns the **same chunks, in
  the same order, with the same scores and metadata** as the original code.

### 5.3 Cache query embeddings

**File:** `src/embeddings/semantic_search.py`

- **What:** `QueryEmbeddingCache` is a small least-recently-used (LRU) cache.
  It holds at most 256 entries, and each entry expires after 1 hour.
- **Key:** the model name plus the exact question text. An embedding depends
  only on those two inputs, so a cached value can never carry one customer's
  data into another customer's request.
- **Safety:** cached arrays are read-only. **Answers, validation results and
  retrieval results are not cached.**
- **Effect:** a retry, or the same question asked again, skips re-encoding
  (~10 ms each time).

### 5.4 Reuse the query analysis

**Files:** `src/rag/answer_question.py`, `src/embeddings/semantic_search.py`,
`src/agents/rag_agent.py`

- **What:** the router's `QueryAnalysis` is passed into retrieval instead of
  being recomputed. The conflict check and the retrieval filters therefore
  always use the same analysis.
- **Compatibility:** the new `analysis` argument is optional. Existing callers
  such as `evaluate_rag.py` work unchanged.

### 5.5 Share one OpenAI client

**File:** `src/llm/client.py` (new)

- **What:** `get_openai_client()` creates one client per process, which reuses
  HTTPS connections. It is created lazily, so importing the agent no longer
  requires `OPENAI_API_KEY`, which makes offline testing possible.
- **Timeout:** each LLM call times out after 60 s
  (`OPENAI_TIMEOUT_SECONDS`). Before, there was no explicit limit.

### 5.6 Retry only when a retry can help

**File:** `src/agents/rag_agent.py`

The two-attempt limit is unchanged. What changed is *when* a retry happens.
The agent now records why an attempt failed, and the router decides from that
reason:

| Failure reason | What happens now | Why |
|---|---|---|
| `citation`: citation labels missing or invalid | Retry once | A new generation can fix formatting |
| `unsupported`: validator rejected the answer | Retry **only if** the wider search (8 chunks instead of 5) adds chunks not already seen; otherwise abstain | The same evidence would produce the same result |
| `no_evidence`: retrieval found nothing | Abstain, no retry | The same filters find nothing again |
| `validator_error`: validator crashed or returned invalid JSON | Abstain, no retry | Regenerating the answer does not fix the validator |

The "would a retry add evidence?" check repeats only the retrieval step. That
takes a few milliseconds and makes no LLM call, because the query embedding is
cached.

Conflict handling is unchanged: a verified customer/loan mismatch still stops
the request before any retrieval or LLM call.

### 5.7 Lower reasoning effort for answer generation only

**File:** `src/rag/answer_question.py`

- **What:** the answer-generating call now uses `reasoning: {"effort": "low"}`
  (`ANSWER_REASONING_EFFORT`, default `low`).
- **Why this is safe:** every answer is still checked by the evidence
  validator, which keeps its **default** reasoning effort. If a quicker answer
  were wrong or unsupported, the validator would reject it, and the user would
  get a retry or an abstention, not a wrong answer marked as verified.
- **Effect:** generation median 3,943 ms → 1,945 ms, p95 7,406 ms → 3,264 ms.
  Median reasoning tokens fell from ~190 to ~64. All 18 regression checks
  still passed, and the validator approved every answer.
- **The model itself was not changed.** It is still `gpt-5-mini`.

### 5.8 Output-token limits

**Files:** `src/rag/answer_question.py`, `src/agents/rag_agent.py`

| Call | Largest measured output | Limit set |
|---|---|---|
| Answer generation | ~550 tokens | 2,000 (`ANSWER_MAX_OUTPUT_TOKENS`) |
| Evidence validation | ~1,400 tokens | 4,000 (`VALIDATION_MAX_OUTPUT_TOKENS`) |

The limits sit well above normal use. They only stop a runaway response from
taking minutes. If a validation response were ever cut off, it would fail
JSON parsing and the agent would abstain. It would never mark the answer as
verified.

### 5.9 Complete identifier-conflict data

**File:** `src/retrieval/query_analyzer.py`

- **What:** the analyzer now loads verified customer names and loan→customer
  links from `data/raw/enterprise_csv/customers.csv` and
  `loan_applications.csv`, once per process. The previous hardcoded entries
  are kept as a fallback.
- **Why:** the hardcoded lists had no entry for Nina Jansen (NB-CUST-3003) or
  NB-LOAN-2103, so a question mixing her with another customer's loan was not
  caught as a conflict. It now is, deterministically, before any LLM call.

---

## 6. Results after the changes

### 6.1 Warm requests (median / p95, 15 requests each)

| Stage | Before | After |
|---|---|---|
| Embedding model load | 4,640 / 4,897 ms | 0 (startup only) |
| Read embeddings file | 16 / 25 ms | 0 (in memory) |
| Query embedding + vector search | ~15 ms | ~1 ms |
| Answer generation (LLM) | 3,943 / 7,406 ms | **1,945 / 3,264 ms** |
| Evidence validation (LLM) | 8,158 / 15,500 ms | 8,751 / 16,063 ms (unchanged code) |
| **Total** | **17,402 / 24,861 ms** | **11,520 / 17,845 ms** |
| Conflict question | ~6 ms | 3–6 ms |

### 6.2 Cold start

| | Before | After |
|---|---|---|
| Server restart → healthy | 1.3 s | 6.0 s (model now loads at startup) |
| First request after restart | 23.0 s | 7.8 s |

The cold-start figures are single measurements.

### 6.3 A note on noise

LLM response times vary a lot between runs. With **identical** validator code,
the validation median measured 8.2 s, 9.6 s, 11.4 s and 8.8 s in different
rounds. Differences under about 2 s in the LLM stages should therefore be
treated as noise at this sample size. The model-load saving (4.6 s on every
request) and the generation speed-up (about 2×) are well beyond that range.

---

## 7. Remaining bottleneck

> **Update:** this was addressed in a second phase. See
> [Section 12](#12-phase-2-evidence-validation). The text below describes
> the state after phase 1.

**Evidence validation is now about 75% of response time** (median ~8.8 s,
p95 ~16 s). About 84% of its output is reasoning tokens.

Its reasoning effort can be lowered with `VALIDATION_REASONING_EFFORT=low`.
This was **deliberately not done**. The regression checks test whether
*answers* are right, not whether the validator still *catches wrong answers*,
so a weaker validator could pass every check while letting bad answers
through.

Recommended next step:

1. Build a small set of deliberately wrong or unsupported answers, such as a
   wrong salary or a claim attributed to the wrong customer.
2. Confirm the validator rejects all of them at the default effort.
3. Re-run at `low` effort.
4. Change the default only if every bad answer is still rejected.

Other possible improvements, not yet implemented:

- **Stream the answer to the browser** while validation runs. This would
  improve perceived speed, but needs a clear "not yet verified" state in the UI.
- **Structured JSON output for the validator.** This would remove parsing
  failures, which currently cause abstentions.

---

## 8. Correctness safeguards

### 8.1 Live regression checks (real API, real LLM)

**18 of 18 checks passed** both before and after the changes:

- Lotte van Dijk's annual gross salary is **EUR 72,000**, with valid citations.
- Thomas de Boer's monthly gross salary is **EUR 6,750**, with valid citations.
- Tenure: the answer begins **"No"** and cites the 3 May 2021 start date. It
  does not claim 10 years.
- Favorite colour: the answer **states the documents do not contain it** and
  names no colour.
- Thomas de Boer + NB-LOAN-2101: **detected as a conflict**, with no answer and
  no sources.
- Lotte's net salary is **EUR 4,300**, and every citation maps to a returned
  NB-LOAN-2101 source.

### 8.2 Offline tests (`tests/`, no API key needed)

**31 of 31 passed.** The LLM is replaced by a fake, so every path is
deterministic.

| File | What it verifies |
|---|---|
| `test_agent.py` | Conflicts stop before any LLM call; a supported answer finishes in 1 attempt; the router's analysis is reused; retries stop at 2; no retry without evidence; retry only when new evidence exists; a validator crash or invalid output leads to abstention; generation errors propagate |
| `test_api.py` | Response contract unchanged; timing fields present in development and hidden in production; timeouts and errors return HTTP 500 with **no** validation status; blank questions are rejected |
| `test_retrieval.py` | Model loaded once; repeated questions not re-encoded; cache eviction, expiry and read-only values; new search returns identical results to the original; CSV-based conflict detection |
| `test_timing.py` | Stages recorded with attempt numbers; failed stages still recorded |

No question needed a retry during the live runs, so retry behaviour is
covered by the offline tests only.

---

## 9. Configuration reference

| Environment variable | Default | Purpose |
|---|---|---|
| `NEXABANK_ENV` | `development` | Set to `production` to hide `timings_ms` and `token_usage` from API responses |
| `OPENAI_TIMEOUT_SECONDS` | `60` | Per-call timeout for LLM requests |
| `ANSWER_REASONING_EFFORT` | `low` | Reasoning effort for answer generation |
| `ANSWER_MAX_OUTPUT_TOKENS` | `2000` | Output-token limit for answer generation |
| `VALIDATION_REASONING_EFFORT` | `low` | Reasoning effort for evidence validation (chosen in Section 12) |
| `VALIDATION_STRUCTURED_OUTPUT` | `false` | Ask the API to enforce the verdict's JSON schema (no speed benefit measured) |
| `VALIDATION_MAX_OUTPUT_TOKENS` | `4000` | Output-token limit for evidence validation |

---

## 10. How to reproduce

```bash
# Backend (project root)
uv run uvicorn src.api.main:app --reload

# Offline tests (no API key needed)
uv run pytest

# Live benchmark (backend must be running; uses the OpenAI key on the server)
uv run python scripts/latency_benchmark.py --runs 3 --label mytest
uv run python scripts/latency_benchmark.py --cold --label mytest-cold
```

Reports are written to `data/benchmarks/latency_<label>.json`.

---

## 11. Files changed

| File | Change |
|---|---|
| `src/observability/timing.py` | **New.** Per-request stage timing and token-usage logging |
| `src/llm/client.py` | **New.** Shared OpenAI client with a timeout |
| `src/embeddings/semantic_search.py` | Load-once model and embeddings, query-embedding cache, warm-up, analysis reuse |
| `src/rag/answer_question.py` | Shared client, `retrieve_evidence()`, analysis reuse, reasoning effort and output limit |
| `src/agents/rag_agent.py` | Failure reasons, targeted retry rules, shared client, validator output limit, timing |
| `src/api/main.py` | Startup warm-up, request timer, `X-Request-ID`, optional dev timing fields |
| `src/retrieval/query_analyzer.py` | Verified customers and loans loaded from the enterprise CSVs |
| `scripts/latency_benchmark.py` | **New.** Live latency and regression benchmark |
| `tests/` | **New.** 31 offline tests |
| `data/benchmarks/` | **New.** Before/after benchmark reports |
| `pyproject.toml`, `uv.lock` | `pytest` added as a development dependency |

---

## 12. Phase 2: evidence validation

After phase 1, evidence validation was ~75% of response time. This phase
measured it in detail and made it faster without weakening it.

### 12.1 Why validation took 8–16 seconds

Validation was split into timed sub-stages (`evidence_validation.prompt_prep`,
`.llm_request`, `.server_processing`, `.parse`). Server processing comes from
OpenAI's `openai-processing-ms` response header. Results for the original
validator, over 30 validations:

| Sub-stage | Median | p95 |
|---|---|---|
| Building the prompt | 0.0 ms | 0.0 ms |
| OpenAI server processing | 7,663 ms | 11,686 ms |
| Network and client overhead | ~400 ms | |
| Parsing the verdict | 0.0 ms | 0.0 ms |
| **Total** | **8,426 ms** | **12,230 ms** |

- Exactly **one** LLM call per validation, with no SDK retries observed.
- About 95% of the time is **inside the model**, mostly ~580 hidden
  reasoning tokens at the default reasoning effort.
- Validation time correlated only weakly with output length (r = 0.28) and
  not with prompt length, so trimming the prompt would not help. The prompt is
  ~570 tokens of fixed rules plus ~150 tokens of evidence, and it does not
  duplicate anything sent to the answer generator. It was left unchanged.

### 12.2 Changes

1. **Detailed timing** for each validation sub-stage, plus SDK retry counts,
   via `create_response()` in `src/llm/client.py`.
2. **Validator split into steps** in `src/agents/rag_agent.py`:
   `build_validation_prompt()`, `run_evidence_validation()` and
   `parse_validation_output()`. The prompt text is byte-for-byte unchanged.
3. **New deterministic checks** in basic validation, which runs before the
   LLM. Every cited source must have file and document-type metadata. If the
   question names a customer or loan, a cited source belonging to a different
   one fails immediately, with no LLM call. Sources with no ID (e.g. some CSV
   records) are left to the semantic validator.
4. **Validator reasoning effort lowered to `low`**, based on the benchmark
   below. The model is unchanged (`gpt-5-mini`).
5. **A development-only `POST /dev/validate` endpoint** runs just the
   validator, with optional model, effort and output-format overrides, for
   benchmarking. It returns 404 when `NEXABANK_ENV=production`.

Identifier conflicts were already stopped before any retrieval or LLM call.
This was confirmed again: the conflict question took 3–6 ms.

### 12.3 Choosing the validator setting

`scripts/validator_benchmark.py` builds real evidence with the retrieval
pipeline and pairs it with **known-correct and known-wrong answers**, for
example wrong amounts, swapped digits, an overstated tenure, an invented
favourite colour, a fact attributed to the wrong person, a wrong employer, and
an unsupported "approved" claim. A setting is acceptable only if it accepts
every correct answer and rejects every wrong one.

**Standard set: 15 cases × 2 runs**

| Validator config | Correct | Wrong answers accepted | Right answers rejected | Median / p95 |
|---|---|---|---|---|
| `gpt-5-mini`, default effort (original) | 30/30 | 0 | 0 | 8,426 / 12,230 ms |
| `gpt-5-mini`, **low** effort | 30/30 | 0 | 0 | 4,581 / 8,178 ms |
| `gpt-5-mini`, minimal effort | 30/30 | 0 | 0 | 2,337 / 3,808 ms |
| `gpt-5-mini` + structured output | 30/30 | 0 | 0 | 7,649 / 12,338 ms |
| `gpt-5-nano`, default effort | 28/30 | **1** | 1 | 9,234 / 14,733 ms |
| `gpt-5-nano`, low effort | 26/30 | 0 | 4 | 3,555 / 5,203 ms |

**Harder set: 6 cases × 3 runs.** Two of these cases are judgement calls, so
they are compared with the original validator's decision.

| Case | Original | Low | Minimal |
|---|---|---|---|
| Two facts, both right | accept ×3 | accept ×3 | accept ×3 |
| Two facts, one wrong | reject ×3 | reject ×3 | reject ×3 |
| Wrong employer | reject ×3 | reject ×3 | reject ×3 |
| Unsupported "approved" claim | reject ×3 | reject ×3 | reject ×3 |
| Correct value, cited chunk debatable | accept ×3 | accept ×3 | accept ×3 |
| Credit status attributed to Lotte by metadata only | reject ×3 | reject ×3 | **accept ×3** |

**Decision:**
- **`low`** agreed with the original validator on all 48 decisions, at about half the latency.
- **`minimal`** was faster but changed an identity-linkage decision, which is exactly what the validator is for.
- **`gpt-5-nano`** accepted a wrong salary.
- Structured output gave no speed benefit.

So `low` is the default, and the others were rejected.

### 12.4 Results (full API, same six regression questions)

Warm requests, median / p95, 15 LLM-backed requests each:

| Stage | Original | End of phase 1 | End of phase 2 |
|---|---|---|---|
| Answer generation | 3,943 / 7,406 ms | 1,945 / 3,264 ms | 2,311 / 3,658 ms |
| Evidence validation | 8,158 / 15,500 ms | 8,751 / 16,063 ms | **4,604 / 5,746 ms** |
| **Total** | **17,402 / 24,861 ms** | **11,520 / 17,845 ms** | **7,156 / 8,536 ms** |

- Validation now uses a median of ~355 output tokens (~256 of them
  reasoning), down from ~840 (~700).
- Prompt preparation and parsing still take ~0 ms.
- **Regression checks: 18/18 passed.** The conflict question still takes 3–6 ms.

Cold start (single samples):

| | Original | End of phase 1 | End of phase 2 |
|---|---|---|---|
| Server restart → healthy | 1.3 s | 6.0 s | 8.6 s |
| First request | 23.0 s | 7.8 s | 7.4 s |

The startup difference between phases 1 and 2 is within run-to-run variation;
nothing was added to startup in phase 2.

### 12.5 Limits of this evaluation

- The validator benchmark has 21 cases and 2–3 runs each, built from this
  project's synthetic documents. It shows that `low` effort did not change
  any decision **on these cases**. It cannot prove equivalence on every
  possible question.
- Re-run `scripts/validator_benchmark.py` after any change to the validator
  prompt, the model, or the documents.

```bash
# Development server must be running
uv run python scripts/validator_benchmark.py --runs 2 --config current:: --config low::low
uv run python scripts/validator_benchmark.py --hard --runs 3 --config current:: --config low::low
```

---

## Glossary

**Abstain / abstention** — The assistant declines to give an answer because it
cannot verify one against the documents, and says so instead of guessing.

**Agent / LangGraph** — LangGraph is a library for building multi-step AI
workflows as a graph of steps ("nodes") with decisions between them. The
NexaBank *agent* is that workflow: route → answer → validate → finish, retry
or abstain.

**Attempt** — One pass through answer generation and validation. At most two
attempts are allowed per question.

**Basic validation** — A fast, rule-based check that the answer cites sources
and that every citation label (e.g. `[S1]`) refers to a source that was
actually retrieved. No LLM is involved.

**Cache** — Temporary storage of a computed result so it can be reused
instead of recomputed.
- **LRU (least recently used):** when the cache is full, the entry unused for
  the longest time is removed.
- **TTL (time to live):** how long an entry stays valid before it expires.

**Chunk** — A small piece of a document (here, roughly 160 characters). Search
works on chunks rather than whole documents.

**Citation label** — A tag such as `[S1]` in an answer, pointing to the first
retrieved source. `S2` is the second, and so on.

**Cold start** — The first request after the server starts, when nothing is
loaded or cached yet. Usually slower than later requests.

**Context (LLM context)** — The retrieved evidence placed into the prompt
that the LLM reads before answering.

**Cosine similarity** — A score from −1 to 1 measuring how similar two
embeddings are. Higher means more similar. It is used to rank chunks against
the question.

**Deterministic check** — A rule implemented in code that always gives the
same result for the same input, with no LLM involved, e.g. "the cited source
belongs to the customer named in the question".

**Embedding** — A list of numbers (768 here) that represents the meaning of a
piece of text, so that texts with similar meanings get similar numbers.

**Embedding model** — The model that turns text into embeddings. This project
uses `BAAI/bge-base-en-v1.5`, which runs locally.

**Evidence validation** — A second LLM call that independently checks whether
the retrieved evidence supports every claim in the answer, including whether a
named person is reliably linked to the customer or loan ID.

**Evidence validator benchmark** — A test set of known-correct and
known-wrong answers used to check that a validator setting still accepts
the right answers and rejects the wrong ones.

**Exact search** — Literal text matching (like Ctrl+F) across all documents,
used for questions such as "Does 'X' appear anywhere?"

**Identifier conflict** — A question that pairs a customer with a loan that
belongs to someone else (e.g. Thomas de Boer + NB-LOAN-2101). It is detected
from verified data and refused before any retrieval or LLM call.

**False accept / false reject** — A validator accepting a wrong answer (the
dangerous error) / rejecting a correct one (causes an unnecessary abstention).

**Instrumentation** — Code added to measure and record what the system is
doing, here how long each stage takes.

**Latency** — The time between sending a question and receiving the answer.

**Lifespan (FastAPI)** — Code that runs once when the server starts (and
stops). Used here to load the embedding model before the first request.

**LLM (large language model)** — The AI model that writes and checks answers.
Here, OpenAI's `gpt-5-mini`.

**Median** — The middle value when all measurements are sorted. Half of
requests were faster and half slower. It is less affected by outliers than
the average.

**Metadata filter** — Narrowing the search to chunks that belong to a specific
customer, loan or document type before ranking them.

**Output-token limit (`max_output_tokens`)** — The maximum number of tokens
the LLM may produce in one response, reasoning tokens included.

**p95 (95th percentile)** — The time under which 95% of requests finished.
It describes the slow tail that users occasionally experience.

**`perf_counter`** — Python's high-resolution timer (`time.perf_counter()`),
designed for measuring short durations accurately.

**Query analysis** — Rule-based parsing of the question to find customer
names, customer IDs, loan IDs and the likely document type. It is used for
filters and conflict detection.

**RAG (retrieval-augmented generation)** — Answering a question by first
retrieving relevant documents and then having an LLM write an answer using
only that evidence.

**Reasoning effort / reasoning tokens** — Reasoning models such as
`gpt-5-mini` "think" by generating hidden tokens before writing the visible
answer. Reasoning effort (`minimal`, `low`, `medium`, `high`) controls how much
of this they do. Fewer reasoning tokens means a faster response.

**Regression test** — A test that checks previously working behaviour still
works after a change.

**Request ID** — A short unique identifier assigned to each request, used to
connect all log lines that belong to it.

**Retry** — Running another attempt after a failed one. Retries now happen
only when the failure is one that another attempt can fix.

**Semantic search / vector search** — Finding chunks whose meaning is closest
to the question, by comparing embeddings rather than matching exact words.

**Server processing time** — How long OpenAI reports spending on a request
(`openai-processing-ms` header). The difference from the client-side time is
network and connection overhead.

**Singleton** — A resource created only once and then shared, here the
embedding model and the OpenAI client.

**Structured output** — An API option that forces the model's reply to match
a given JSON schema.

**Stage** — One measured step of request processing, such as
`answer_generation` or `evidence_validation`.

**Token** — The unit LLMs read and write, roughly ¾ of an English word. LLM
time and cost grow with the number of tokens.

**Warm request** — A request made after the server has already loaded its
models and caches. This is the normal case.

**Warm-up** — Doing slow one-time work (loading the model, a first encode)
at startup, so users do not wait for it.
