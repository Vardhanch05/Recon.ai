# task_today.md
## Current Build Session — Settlement Reconciler

Last updated: start of build session. Update checkboxes as you go.

---

## Priority Order (Follow This)

Build in this sequence. Do not skip ahead — each phase unlocks the next.

---

## Phase 1: DB + Ingestion

- [ ] Write DDL migrations — run and verify all tables, enums, constraints, indexes exist
- [ ] Implement `POST /batches/upload` — accepts `settlement_file` + `ledger_file` multipart
- [ ] Parse settlement CSV: validate required fields, handle malformed rows
- [ ] Parse ledger CSV: same validation
- [ ] Write `settlement_records` rows to DB
- [ ] Write `order_ledger` rows to DB
- [ ] Write `audit_log` entry for each ingestion_error
- [ ] Increment `batches.ingestion_error_count` for skipped rows
- [ ] Handle duplicate batch (same files): return 409, prompt confirm
- [ ] Smoke test: upload CSVs, verify row counts in DB

---

## Phase 2: Deterministic Matching

- [ ] Implement `POST /batches/{id}/run-matching`
- [ ] Primary path: null-safe order_id query
- [ ] Confirm order_id match: unconditional if no fee_deducted; sanity flag if fee_deducted present
- [ ] If sanity fails → route `amount_mismatch`, preserve order_ledger_id on result row
- [ ] Fallback path: only runs if fee_deducted IS NOT NULL
- [ ] Fallback: fee-adjusted amount + timestamp window query
- [ ] Handle ambiguous_multiple: insert all candidates into `exception_candidates` table
- [ ] Handle currency_mismatch: route with reason
- [ ] Handle no_match: route with reason
- [ ] Write all `reconciliation_results` rows with correct routing_reason
- [ ] Update `batches.status` → `matching_complete`
- [ ] Compute and write `batches.match_rate_deterministic`
- [ ] Log each match to `audit_log`
- [ ] Idempotency: use upsert on UNIQUE(batch_id, settlement_record_id)
- [ ] Smoke test: verify ~40 of 55 synthetic records match

---

## Phase 3: Synthetic Dataset

- [ ] Generate `data/synthetic_batch.csv` (55 records)
  - 40 clean matches with order_ids
  - 7 discrepancy records (domestic MDR, intl MDR, GST-on-fee, partial refund, flat surcharge, 1 combined)
  - 3 unresolvable (₹200+ gap, nonsensical)
- [ ] Generate `data/ledger.csv` (matching ledger side)
- [ ] Generate `data/ground_truth.csv` — category + true_cause per non-trivial record (keep separate from reasoner)
- [ ] Run Phase 2 against synthetic data — verify ~40 records auto-match
- [ ] Note actual residual_gap values from explainable records → calibrate ₹5.00 threshold if needed

---

## Phase 4: LLM Reasoner

- [ ] Register `calculate_difference` as LLM function tool
- [ ] Write context builder for single-candidate exceptions
- [ ] Write context builder for ambiguous_multiple exceptions (candidate_orders array)
- [ ] Include `payment_method` in candidate_order context
- [ ] Write system prompt: hypothesis selection → tool call → gap check → UNRESOLVED if needed
- [ ] Implement LLM call with tool-calling enabled
- [ ] Implement retry on timeout (once); fallback to UNRESOLVED on second failure
- [ ] Implement `compute_confidence()` function
- [ ] Implement `validate_card()` — must override LLM output before DB write
- [ ] Implement `POST /batches/{id}/run-reasoning` as async background task
- [ ] Use LangChain `.batch()` for parallel processing
- [ ] Write `reasoning_cards` rows
- [ ] Write `reconciliation_results` updates (matched_ai_resolved or exception_unresolved)
- [ ] Update `batches.status` → `reasoning_complete`
- [ ] Log each llm_call to `audit_log`
- [ ] Smoke test: run against 7 discrepancy records, check categories match ground_truth

---

## Phase 5: Summary + Exceptions API

- [ ] Implement `GET /batches/{id}/summary` — full response schema per TRD
- [ ] Implement `GET /batches/{id}/exceptions` — paginated, includes reasoning cards
- [ ] Verify frontend can poll /summary and detect completion

---

## Phase 6: Human Approval + Dashboard

- [ ] Implement `POST /reconciliation/{id}/approve` — atomic guard, 409 on double-action
- [ ] Implement `POST /reconciliation/{id}/reject` — same pattern, record reviewed_by
- [ ] Journal posting on approve
- [ ] Log human_approval / human_rejection / journal_posted to audit_log
- [ ] Build `<UploadPanel />` — two file inputs, upload CTA
- [ ] Build `<PipelineStepper />` — 4 steps, driven by batch.status
- [ ] Build `<MatchRateSummaryCard />` — 3 stats + throughput timer
- [ ] Build `<ReasoningCard />` — hypothesis + math table + confidence badge + approve/reject
- [ ] Math table expandable: billed, fee%, GST%, expected, actual, gap
- [ ] Confidence badge: green/amber/red based on score
- [ ] Handle 409 on double-action: toast notification
- [ ] Rejected card: distinct visual state, shows override note if present

---

## Phase 7: Audit Log + Accuracy Report

- [ ] Build `<AuditLogViewer />` — filterable by event_type + date range
- [ ] Implement `GET /batches/{id}/audit-log` with filter params
- [ ] Implement `GET /batches/{id}/accuracy-report`:
  - Accept ground_truth.csv path
  - Join against reasoning_cards.suggested_category
  - Return confusion matrix
- [ ] Test: run full pipeline → approve all → check accuracy report shows 7/7 + 3/3

---

## Done When

- [ ] Upload → Match → Reason → Approve full flow works end-to-end on synthetic data
- [ ] MatchRateSummaryCard shows 80% / ~14% / ~6%
- [ ] Accuracy report confirms all 10 non-trivial records correctly handled
- [ ] Audit log shows full event trail including human approvals
- [ ] No duplicate journal entries possible (409 verified)
