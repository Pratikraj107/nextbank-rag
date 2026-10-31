# NexaBank AI — Evaluation Summary

- **Run:** `20261025T113528Z` (2026-10-25T11:35:28+00:00)
- **Agent:** running API at http://127.0.0.1:8000 (real agent over HTTP)
- **Git commit:** `1521b18` (uncommitted changes present)
- **Dataset:** `data/evaluation/nexabank_eval.jsonl` (sha256 `02e0683c23d2`), 28 cases run
- **Latency measurement:** warm requests to an already-running API (includes HTTP overhead); 1 warm-up request(s) excluded from all metrics. Process cold start is not measured.

## Headline metrics

| Metric | Result |
|---|---|
| Overall pass (behaviour + citations) | 100.0% (28/28) |
| Behaviour pass | 100.0% (28/28) |
| Exact-fact accuracy (reference facts in answer cases) | 100.0% (19/19) |
| Correct abstention (abstain cases) | 100.0% (6/6) |
| Abstention precision (abstentions that were warranted) | 100.0% (6/6) |
| Incorrect answers to abstain cases | 0.0% (0/6) |
| Over-abstention (answer cases not answered) | 0.0% (0/19) |
| Conflict rejection | 100.0% (3/3) |
| Conflicts stopped before generation | 100.0% (3/3) |
| Citation labels map to returned sources | 100.0% (25/25) |
| Required citation present | 100.0% (19/19) |
| Source metadata complete (per source) | 100.0% (86/86) |
| Expected source type cited | 100.0% (18/18) |
| Cited sources match expected customer/loan | 100.0% (19/19) |
| Expected value found in a cited chunk (heuristic) | n/a (0 cases) |
| Basic validation passed | 89.3% (25/28) |
| Evidence validation passed | 89.3% (25/28) |
| Errors | 0 |

Citation mapping only checks that each label points to a returned source. It does not prove the source supports the claim; the "found in a cited chunk" row is a literal-match heuristic, and only available when chunk text is returned.

## Validation outcomes

Identifier conflicts are refused before any validation runs, so they report both validation flags as false; that is expected, not a validation failure.

| Outcome | Cases |
|---|---|
| identifier_conflict | 3 |
| verified_abstention | 6 |
| verified_answer | 19 |

## Latency

| Requests | n | Median | Mean | Min | Max | p95 |
|---|---|---|---|---|---|---|
| All completed | 28 | 5,762 ms | 5,638 ms | 3 ms | 8,470 ms | 8,158 ms |
| LLM-backed (conflict refusals excluded) | 25 | 6,046 ms | 6,314 ms | 4,994 ms | 8,470 ms | 8,229 ms |

## By category

| Category | Passed | Median latency | n | Mean attempts | Max attempts |
|---|---|---|---|---|---|
| abstention | 100.0% (3/3) | 6,914 ms | 3 | 1.0 | 1 |
| citation_mapping | 100.0% (2/2) | 5,338 ms | 2 | 1.0 | 1 |
| dates_tenure | 100.0% (3/3) | 6,326 ms | 3 | 1.0 | 1 |
| identifier_conflict | 100.0% (3/3) | 5 ms | 3 | 0.0 | 0 |
| insufficient_evidence | 100.0% (3/3) | 7,389 ms | 3 | 1.0 | 1 |
| loan_attribution | 100.0% (1/1) | 6,046 ms | 1 | 1.0 | 1 |
| numeric_precision | 100.0% (5/5) | 5,618 ms | 5 | 1.0 | 1 |
| supported_fact | 100.0% (5/5) | 5,842 ms | 5 | 1.0 | 1 |
| unsupported_status | 100.0% (1/1) | 5,014 ms | 1 | 1.0 | 1 |
| wrong_employer | 100.0% (1/1) | 5,430 ms | 1 | 1.0 | 1 |
| wrong_person | 100.0% (1/1) | 5,356 ms | 1 | 1.0 | 1 |

## Failed cases

None.

## Needs manual review

- **`tenure_lotte_ten_years_not_overstated`**: answer contains both the expected facts and declining language
- **`status_loan_2101_not_approved`**: answer contains both the expected facts and declining language

## Comparison with baseline

Baseline run `20261025T111907Z`; 25 matching test IDs compared.

⚠️ **The dataset changed between the two runs.** Result changes for a test ID may come from an edited test definition rather than from the agent.

- Passed (matching IDs): 24 → 25
- Newly failing: none
- Newly passing: ['insufficient_loan_2101_monthly_instalment']
- Behaviour changed: ['insufficient_loan_2101_monthly_instalment']
- Median latency (matching IDs): 5,750 ms → 5,618 ms
- Added test IDs (not compared): ['insufficient_loan_2102_monthly_instalment', 'insufficient_loan_2103_monthly_repayment', 'loan_attribution_existing_payment_lotte']
- Removed test IDs (not compared): none

## Per-case results

| ID | Expected | Actual | Pass | Latency | Attempts |
|---|---|---|---|---|---|
| `fact_lotte_annual_gross_salary` | answer | answer | ✅ | 5,401 ms | 1 |
| `fact_thomas_monthly_gross_salary` | answer | answer | ✅ | 5,842 ms | 1 |
| `fact_lotte_monthly_net_salary` | answer | answer | ✅ | 6,340 ms | 1 |
| `fact_thomas_monthly_net_salary` | answer | answer | ✅ | 5,616 ms | 1 |
| `fact_nina_annual_gross_salary` | answer | answer | ✅ | 6,829 ms | 1 |
| `amount_nina_monthly_gross_decimal` | answer | answer | ✅ | 7,472 ms | 1 |
| `amount_lotte_outstanding_balance` | answer | answer | ✅ | 8,323 ms | 1 |
| `amount_thomas_outstanding_balance` | answer | answer | ✅ | 5,578 ms | 1 |
| `amount_loan_2101_requested` | answer | answer | ✅ | 5,618 ms | 1 |
| `quantity_loan_2101_term` | answer | answer | ✅ | 5,530 ms | 1 |
| `date_lotte_employment_start` | answer | answer | ✅ | 5,190 ms | 1 |
| `tenure_lotte_ten_years_not_overstated` | answer | answer | ✅ | 8,470 ms | 1 |
| `date_lotte_date_of_birth` | answer | answer | ✅ | 6,326 ms | 1 |
| `abstain_lotte_favorite_color` | abstain | abstain | ✅ | 6,914 ms | 1 |
| `abstain_lotte_spouse_name` | abstain | abstain | ✅ | 7,135 ms | 1 |
| `abstain_thomas_credit_score` | abstain | abstain | ✅ | 6,864 ms | 1 |
| `conflict_thomas_with_loan_2101` | reject_conflict | reject_conflict | ✅ | 6 ms | 0 |
| `conflict_lotte_with_loan_2102` | reject_conflict | reject_conflict | ✅ | 5 ms | 0 |
| `conflict_customer_id_3002_with_loan_2101` | reject_conflict | reject_conflict | ✅ | 3 ms | 0 |
| `wrong_person_thomas_salary_is_lottes` | answer | answer | ✅ | 5,356 ms | 1 |
| `wrong_employer_lotte_delta_infra` | answer | answer | ✅ | 5,430 ms | 1 |
| `status_loan_2101_not_approved` | answer | answer | ✅ | 5,014 ms | 1 |
| `citation_lotte_iban` | answer | answer | ✅ | 5,682 ms | 1 |
| `citation_loan_2101_offer_principal` | answer | answer | ✅ | 4,994 ms | 1 |
| `insufficient_loan_2101_monthly_instalment` | abstain | abstain | ✅ | 7,850 ms | 1 |
| `loan_attribution_existing_payment_lotte` | answer | answer | ✅ | 6,046 ms | 1 |
| `insufficient_loan_2102_monthly_instalment` | abstain | abstain | ✅ | 6,638 ms | 1 |
| `insufficient_loan_2103_monthly_repayment` | abstain | abstain | ✅ | 7,389 ms | 1 |
