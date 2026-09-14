# task_today.md
## Current Build Session — Settlement Reconciler

Last updated: start of build session. Update checkboxes as you go.

---

## Priority Order (Follow This)

Build in this sequence. Do not skip ahead — each phase unlocks the next.

---

## Phase 1: DB + Ingestion

- [x] Write DDL migrations — run and verify all tables, enums, constraints, indexes exist
- [x] Implement `POST /batches/upload` — accepts `settlement_file` + `ledger_file` multipart
- [x] Parse settlement CSV: validate required fields, handle malformed rows
- [x] Parse ledger CSV: same validation
- [x] Write `settlement_records` rows to DB
- [x] Write `order_ledger` rows to DB
- [x] Write `audit_log` entry for each ingestion_error
- [x] Increment `batches.ingestion_error_count` for skipped rows
- [x] Handle duplicate batch (same files): return 409, prompt confirm
- [x] Smoke test: upload CSVs, verify row counts in DB

---

## Phase 2: Deterministic Matching

- [x] Implement `POST /batches/{id}/run-matching`
- [x] Primary path: null-safe order_id query
- [x] Confirm order_id match: unconditional if no fee_deducted; sanity flag if fee_deducted present
- [x] If sanity fails → route `amount_mismatch`, preserve order_ledger_id on result row
- [x] Fallback path: only runs if fee_deducted IS NOT NULL
- [x] Fallback: fee-adjusted amount + timestamp window query
- [x] Handle ambiguous_multiple: insert all candidates into `exception_candidates` table
- [x] Handle currency_mismatch: route with reason
- [x] Handle no_match: route with reason
- [x] Write all `reconciliation_results` rows with correct routing_reason
- [x] Update `batches.status` → `matching_complete`
- [x] Compute and write `batches.match_rate_deterministic`
- [x] Log each match to `audit_log`
- [x] Idempotency: use upsert on UNIQUE(batch_id, settlement_record_id)
- [x] Smoke test: verify ~40 of 55 synthetic records match

---

## Phase 3: Synthetic Dataset

- [x] Generate `data/synthetic_batch.csv` (55 records)
  - 40 clean matches with order_ids
  - 7 discrepancy records (domestic MDR, intl MDR, GST-on-fee, partial refund, flat surcharge, 1 combined)
  - 3 unresolvable (₹200+ gap, nonsensical)
- [x] Generate `data/ledger.csv` (matching ledger side)
- [x] Generate `data/ground_truth.csv` — category + true_cause per non-trivial record (keep separate from reasoner)
- [x] Run Phase 2 against synthetic data — verify ~40 records auto-match
- [x] Note actual residual_gap values from explainable records → calibrate ₹5.00 threshold if needed

---

## Phase 4: LLM Reasoner

- [x] Register `calculate_difference` as LLM function tool
- [x] Write context builder for single-candidate exceptions
- [x] Write context builder for ambiguous_multiple exceptions (candidate_orders array)
- [x] Include `payment_method` in candidate_order context
- [x] Write system prompt: hypothesis selection → tool call → gap check → UNRESOLVED if needed
- [x] Implement LLM call with tool-calling enabled
- [x] Implement retry on timeout (once); fallback to UNRESOLVED on second failure
- [x] Implement `compute_confidence()` function
- [x] Implement `validate_card()` — must override LLM output before DB write
- [x] Implement `POST /batches/{id}/run-reasoning` as async background task
- [x] Use LangChain `.batch()` for parallel processing
- [x] Write `reasoning_cards` rows
- [x] Write `reconciliation_results` updates (matched_ai_resolved or exception_unresolved)
- [x] Update `batches.status` → `reasoning_complete`
- [x] Log each llm_call to `audit_log`
- [x] Smoke test: run against 7 discrepancy records, check categories match ground_truth

---

## Phase 5: Summary + Exceptions API

- [x] Implement `GET /batches/{id}/summary` — full response schema per TRD
- [x] Implement `GET /batches/{id}/exceptions` — paginated, includes reasoning cards
- [x] Verify frontend can poll /summary and detect completion

---

## Phase 6: Human Approval + Dashboard

- [x] Implement `POST /reconciliation/{id}/approve` — atomic guard, 409 on double-action
- [x] Implement `POST /reconciliation/{id}/reject` — same pattern, record reviewed_by
- [x] Journal posting on approve
- [x] Log human_approval / human_rejection / journal_posted to audit_log
- [x] Build `<UploadPanel />` — two file inputs, upload CTA
- [x] Build `<PipelineStepper />` — 4 steps, driven by batch.status
- [x] Build `<MatchRateSummaryCard />` — 3 stats + throughput timer
- [x] Build `<ReasoningCard />` — hypothesis + math table + confidence badge + approve/reject
- [x] Math table expandable: billed, fee%, GST%, expected, actual, gap
- [x] Confidence badge: green/amber/red based on score
- [x] Handle 409 on double-action: toast notification
- [x] Rejected card: distinct visual state, shows override note if present

---

## Phase 7: Audit Log + Accuracy Report

- [x] Build `<AuditLogViewer />` — filterable by event_type + date range
- [x] Implement `GET /batches/{id}/audit-log` with filter params
- [x] Implement `GET /batches/{id}/accuracy-report`:
  - Accept ground_truth.csv path
  - Join against reasoning_cards.suggested_category
  - Return confusion matrix
- [x] Test: run full pipeline → approve all → check accuracy report shows 7/7 + 3/3

---

## Done When

- [x] Upload → Match → Reason → Approve full flow works end-to-end on synthetic data
- [x] MatchRateSummaryCard shows 80% / ~14% / ~6%
- [x] Accuracy report confirms all 10 non-trivial records correctly handled
- [x] Audit log shows full event trail including human approvals
- [x] No duplicate journal entries possible (409 verified)
