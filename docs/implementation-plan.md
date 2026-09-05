# Implementation Plan

## Multi-Source Settlement Reconciler

---

## Build Order (Follow This Exactly)

The order is designed to front-load the two highest-risk components — LLM tool-calling reliability and honest synthetic data — rather than leaving them for the final hours.

---

## Phase 1: DB + Ingestion (Start Here)

**Goal:** Get real data flowing into the database. Everything else depends on this.

Tasks:

- [ ] Write and run full DDL migrations (all tables, enums, indexes, constraints)
- [ ] Implement `POST /batches/upload` — multipart CSV upload, parse both files
- [ ] Write ingestion service: validate rows, handle malformed rows, write to DB
- [ ] Log ingestion errors to `audit_log`
- [ ] Implement duplicate batch detection (return 409 with confirm prompt)
- [ ] Write a simple test: upload sample CSVs, verify DB rows created

Deliverable: upload two CSVs, see rows in `settlement_records` and `order_ledger`.

---

## Phase 2: Deterministic Matching Engine

**Goal:** Achieve the 80% match rate — this alone is a working demo.

Tasks:

- [ ] Implement `POST /batches/{id}/run-matching`
- [ ] Primary path: order_id match (null-safe query)
- [ ] Confirmation logic for order_id path:
  - If `fee_deducted` present: run sanity check; route `amount_mismatch` if fails
  - If no `fee_deducted`: trust order_id unconditionally
- [ ] Fallback path: fee-adjusted amount + timestamp (only when `fee_deducted IS NOT NULL`)
- [ ] Tag all exceptions with `routing_reason`
- [ ] Handle `ambiguous_multiple`: insert into `exception_candidates` table
- [ ] Write `reconciliation_results` rows
- [ ] Update `batches.status` to `matching_complete`, compute `match_rate_deterministic`
- [ ] Log each match to `audit_log`
- [ ] Idempotency: use upsert pattern on `UNIQUE(batch_id, settlement_record_id)`

Deliverable: run matching on sample data, see ~80% of records marked `matched_deterministic`.

---

## Phase 3: Synthetic Dataset with Ground Truth

**Goal:** Build the evaluation data before building the reasoner.

Tasks:

- [ ] Generate 50–60 record batch:
  - ~40 clean 1:1 matches
  - ~7 explainable discrepancies (domestic MDR, intl MDR, GST-on-fee, partial refund, flat surcharge, 1 combined-cause)
  - ~3 deliberately unresolvable (large nonsensical gaps — e.g., ₹200+ discrepancy)
- [ ] Create hidden `ground_truth.csv` with `gateway_txn_id`, `true_category`, `true_cause` per non-trivial record
- [ ] Run dataset through matching engine manually to verify ~40 records auto-match
- [ ] Calibrate `compute_confidence` threshold (₹5.00 band) against actual residual gaps from explainable records

Deliverable: `data/synthetic_batch.csv`, `data/ledger.csv`, `data/ground_truth.csv` (hidden from reasoner).

---

## Phase 4: LLM Reasoner with Tool-Calling

**Goal:** The highest-risk component — start early, expect iteration.

Tasks:

- [ ] Register `calculate_difference` as a function tool with the LLM provider
- [ ] Implement context builder: produces the JSON context object per exception (§5.1)
  - Include `payment_method` in `candidate_order`
  - For `ambiguous_multiple`: produce `candidate_orders: [...]` array from `exception_candidates`
- [ ] Write the LLM prompt — must instruct: select hypothesis, call tool, check residual_gap, output UNRESOLVED if no hypothesis works
- [ ] Implement retry on LLM timeout (once); fallback to UNRESOLVED on second failure
- [ ] Implement `validate_card()` server-side override
- [ ] Implement `POST /batches/{id}/run-reasoning` as async background task
- [ ] Use LangChain `.batch()` to parallelize exception processing
- [ ] Write reasoning cards to DB
- [ ] Update `batches.status` to `reasoning_complete`, compute `match_rate_ai_resolved`
- [ ] Log each LLM call to `audit_log`

Deliverable: run reasoning on 10 exception records, see reasoning cards in DB with correct categories.

---

## Phase 5: Reasoning Card Output + Confidence

Tasks:

- [ ] Implement `compute_confidence(residual_gap)` function
- [ ] Implement `validate_card()` that overrides LLM output with `compute_confidence` result
- [ ] Implement `GET /batches/{id}/exceptions` endpoint with pagination
- [ ] Implement `GET /batches/{id}/summary` — full response schema per TRD
- [ ] Test: upload ground-truth dataset, run full pipeline, compare `suggested_category` against `ground_truth.csv`

---

## Phase 6: Human Approval API + Dashboard UI

Tasks:

- [ ] Implement `POST /reconciliation/{id}/approve` with atomic guard
- [ ] Implement `POST /reconciliation/{id}/reject` with atomic guard (same pattern)
- [ ] Implement journal posting on approve
- [ ] Build React dashboard:
  - `<UploadPanel />`
  - `<Pipeline Stepper />`
  - `<MatchRateSummaryCard />`
  - `<ExceptionList />` with `<ReasoningCard />`
  - Math breakdown table (expandable)
  - Confidence badge with color coding
  - Approve/Reject buttons with state transitions
- [ ] Handle 409 responses gracefully in UI (toast notification)

---

## Phase 7: Audit Log Viewer + Accuracy Report

Tasks:

- [ ] Build `<AuditLogViewer />` with event_type filter and date range filter
- [ ] Implement `GET /batches/{id}/audit-log` with filter params
- [ ] Implement `GET /batches/{id}/accuracy-report`:
  - Accept ground truth CSV upload (or path)
  - Join against `reasoning_cards.suggested_category`
  - Return confusion matrix

---

## Optional Enhancement (if time allows)

- Multi-hypothesis retry loop using LangGraph: try hypothesis 1 → check gap → retry with hypothesis 2 → ... → UNRESOLVED. Makes for a stronger demo ("watch it try three hypotheses").

---

## Time Estimates (Hackathon Context)

| Phase                         | Estimated Time  |
| ----------------------------- | --------------- |
| Phase 1: DB + Ingestion       | 3–4 hours       |
| Phase 2: Matching Engine      | 3–4 hours       |
| Phase 3: Synthetic Dataset    | 2–3 hours       |
| Phase 4: LLM Reasoner         | 4–6 hours       |
| Phase 5: Cards + Confidence   | 2 hours         |
| Phase 6: Approval + Dashboard | 4–5 hours       |
| Phase 7: Audit + Accuracy     | 2–3 hours       |
| Buffer + Demo Prep            | 2–3 hours       |
| **Total**                     | **22–30 hours** |
