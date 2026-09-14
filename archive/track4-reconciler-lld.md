# Low-Level Design: Multi-Source Settlement Reconciler
### Track 4 — AI Finance Controller

---

## 1. System Overview

**Goal:** Ingest a bank settlement file and an internal order ledger, auto-match the majority of records deterministically, use an LLM reasoning agent to explain the remaining discrepancies, and surface a human-approval dashboard with an honest match-rate + exception report.

**High-Level Flow:**
```
Settlement File (CSV) ──┐
                         ├──> Ingestion Service ──> Matching Engine ──┬──> Auto-Reconciled (clean matches)
Order Ledger (CSV/DB) ──┘                                             └──> Exception Queue ──> LLM Reasoner ──> Reasoning Cards ──> Approval Dashboard ──> Ledger Posting
```

---

## 2. Component Breakdown

| Component | Responsibility | Deterministic or AI |
|---|---|---|
| Ingestion Service | Parse/validate settlement + ledger files, normalize into DB rows | Deterministic |
| Matching Engine | Match records within tolerance window (amount, order ID, timestamp) | Deterministic |
| Exception Router | Route unmatched records to the LLM reasoner in batches | Deterministic |
| LLM Discrepancy Reasoner | Explain why a record didn't match, using tool calls for math | AI (with deterministic tool calls) |
| Reasoning Card Generator | Format LLM output into a structured, displayable card | Deterministic (post-processing) |
| Approval Service | Human approve/reject → posts journal entry | Deterministic |
| Audit Logger | Immutable log of every match, exception, LLM call, and human decision | Deterministic |
| Dashboard (React) | Match-rate summary, exception list, reasoning cards, approval UI | Frontend |

---

## 3. Data Model (PostgreSQL)

### 3.1 `settlement_records`
| Column | Type | Notes |
|---|---|---|
| id | UUID (PK) | |
| batch_id | UUID (FK → batches) | |
| gateway_txn_id | VARCHAR | Gateway-side transaction reference |
| order_id | VARCHAR | Merchant order reference (may be null if unparseable); null handled explicitly in matching — `WHERE order_id = NULL` returns zero rows in SQL, so null order_id falls through to amount fallback |
| settled_amount | DECIMAL(12,2) | Amount actually settled |
| settlement_timestamp | TIMESTAMP | **Assumption: this is the original transaction timestamp echoed back by the gateway, not the T+2 credit-posting time.** If your settlement file uses credit-posting time instead, drop timestamp from the fallback match entirely and rely on order_id + amount only. Document your choice in §4.1. |
| fee_deducted | DECIMAL(12,2) | If present in the file — used in fallback amount comparison |
| currency | VARCHAR(3) | |
| raw_row_json | JSONB | Original row, for traceability |

> Constraint: `UNIQUE(batch_id, gateway_txn_id)` — prevents duplicate rows from a CSV with repeated transactions.

### 3.2 `order_ledger`
| Column | Type | Notes |
|---|---|---|
| id | UUID (PK) | |
| batch_id | UUID (FK) | |
| order_id | VARCHAR | |
| billed_amount | DECIMAL(12,2) | What the customer was charged |
| order_timestamp | TIMESTAMP | |
| refund_amount | DECIMAL(12,2) | Nullable |
| is_international | BOOLEAN | Drives FX-related discrepancy logic |
| payment_method | VARCHAR | e.g. `card`, `upi`, `netbanking` — determines applicable MDR rate |
| raw_row_json | JSONB | |

### 3.3 `reconciliation_results`
| Column | Type | Notes |
|---|---|---|
| id | UUID (PK) | |
| batch_id | UUID (FK) | |
| settlement_record_id | UUID (FK, NOT NULL) | Always populated — reconciliation always originates from a settlement record |
| order_ledger_id | UUID (FK, nullable) | Null when no ledger match found |
| status | ENUM | `matched_deterministic`, `matched_ai_resolved`, `exception_unresolved`, `human_approved`, `human_rejected` |
| routing_reason | ENUM | `order_id_match`, `amount_mismatch`, `no_match`, `ambiguous_multiple`, `currency_mismatch` — why this record was routed to exceptions |
| discrepancy_amount | DECIMAL(12,2) | Nullable — 0 for clean matches |
| resolution_source | ENUM | `rule_engine`, `llm_reasoner`, `human_override` |
| confidence_score | DECIMAL(3,2) | Only for AI-resolved rows |
| reviewed_at | TIMESTAMP | Populated on human approve/reject |
| reviewed_by | VARCHAR | User ID of the approving/rejecting accountant |
| created_at | TIMESTAMP | |

> Constraints: `UNIQUE(batch_id, settlement_record_id)` — enforces idempotency on re-runs. `settlement_record_id` is NOT NULL — no orphaned result rows possible.
>
> Note on ambiguous-multiple candidates: `order_ledger_id` is a single FK and cannot hold multiple candidates. For `routing_reason = 'ambiguous_multiple'`, store candidate IDs in a `candidate_order_ids UUID[]` array column (add to schema) or a small `exception_candidates(exception_id, order_ledger_id)` join table. Pass all candidates in the LLM context as `candidate_orders: [...]`.

### 3.4 `reasoning_cards`
| Column | Type | Notes |
|---|---|---|
| id | UUID (PK) | |
| reconciliation_result_id | UUID (FK) | |
| hypothesis_text | TEXT | Human-readable explanation |
| calculation_breakdown | JSONB | Structured math steps (see §5.3) — includes `refund_amount_tested` and `fx_adjustment_tested` fields |
| confidence_score | DECIMAL(3,2) | Computed server-side from `residual_gap` via `compute_confidence()`, never LLM self-reported |
| suggested_category | VARCHAR | `MDR_VARIANCE`, `PARTIAL_REFUND`, `FX_ROUNDING`, `UNRESOLVED` — overridden server-side if inconsistent with `residual_gap` |
| requires_human_review | BOOLEAN | |
| human_override_note | TEXT | Nullable — accountant's reason for rejection |

### 3.5 `audit_log`
| Column | Type | Notes |
|---|---|---|
| id | UUID (PK) | |
| batch_id | UUID | |
| event_type | ENUM | `ingestion_error`, `match`, `llm_call`, `human_approval`, `human_rejection`, `journal_posted` |
| actor | VARCHAR | `system`, `llm`, or a user ID |
| payload_json | JSONB | Full context for that event — immutable |
| timestamp | TIMESTAMP | |

> Index: `(batch_id, timestamp)` — required for audit log viewer queries and event-type filtering.

### 3.6 `batches`
| Column | Type | Notes |
|---|---|---|
| id | UUID (PK) | |
| uploaded_at | TIMESTAMP | |
| status | ENUM | `uploaded`, `matching_complete`, `reasoning_complete`, `failed` — drives frontend pipeline stage buttons |
| total_records | INT | |
| ingestion_error_count | INT DEFAULT 0 | Rows skipped during CSV parsing — surfaced in summary |
| match_rate_deterministic | DECIMAL(5,2) | Computed after Step 1; null until then |
| match_rate_ai_resolved | DECIMAL(5,2) | Computed after Step 2; null until then |
| unresolved_count | INT | |
| timestamp_tolerance_seconds | INT DEFAULT 2 | Fallback match timestamp window — see §4.1 for assumption |

---

## 4. Deterministic Matching Engine (Step 1)

### 4.1 Algorithm
```
for each settlement_record in batch:
    # Step 1: primary match on order_id (null-safe — skip if order_id is null)
    if settlement_record.order_id IS NOT NULL:
        candidates = order_ledger.filter(
            order_id == settlement_record.order_id
        )
    else:
        candidates = []

    # Step 2: fallback on (billed_amount - fee_deducted) ≈ settled_amount + timestamp
    # ASSUMPTION: settlement_timestamp is the original transaction timestamp echoed by
    # the gateway, NOT the T+2 credit-posting time. If it's credit-posting time, remove
    # the timestamp condition and rely on order_id + amount only.
    if no candidates AND settlement_record.fee_deducted IS NOT NULL:
        candidates = order_ledger.filter(
            abs((billed_amount - settlement_record.fee_deducted) - settlement_record.settled_amount) < 0.01
            AND abs(order_timestamp - settlement_record.settlement_timestamp) <= tolerance_window
        )

    # Confirmation logic differs by path — do NOT share a single amount check across both
    if exactly one candidate from order_id path:
        # order_id is a strong, trusted signal — accept the match unconditionally
        # If fee_deducted is present, use it as an optional sanity flag only, not a gate
        if settlement_record.fee_deducted IS NOT NULL:
            sanity_gap = abs(candidate.billed_amount - settlement_record.fee_deducted - settlement_record.settled_amount)
            if sanity_gap >= 0.01:
                # Amount doesn't reconcile even accounting for fee — route as amount_mismatch
                # but preserve the order_id candidate as order_ledger_id for LLM context
                routing_reason = 'amount_mismatch'
                populate order_ledger_id with candidate
                route to exception_queue with routing_reason
                continue
        # Either no fee_deducted (trust order_id alone) or sanity check passed
        mark as matched_deterministic, routing_reason = 'order_id_match'
        write reconciliation_results row
        continue

    elif exactly one candidate from fallback (amount+timestamp) path:
        # Fallback already filtered on fee-adjusted amount — if we're here, it matched
        mark as matched_deterministic, routing_reason = 'amount_match'
        write reconciliation_results row
        continue

    else:
        # Tag the routing reason so the LLM context knows why this is an exception
        if len(candidates) > 1:
            routing_reason = 'ambiguous_multiple'
            # Store all candidate order_ledger_ids for LLM — see §3.3 note on candidate_order_ids
        elif currency mismatch:
            routing_reason = 'currency_mismatch'
        else:
            routing_reason = 'no_match'
        route to exception_queue with routing_reason
```

**Timestamp assumption (must decide before building):** The ±`timestamp_tolerance_seconds` window only makes sense if `settlement_timestamp` is the original transaction time echoed back by the gateway. Real Razorpay settlement files typically carry the transaction timestamp, making ±2 seconds a reasonable deduplication guard. If your file uses the T+2 batch credit-posting timestamp instead, remove the timestamp condition from the fallback entirely — a Monday order and Wednesday settlement will never be within seconds of each other.

**Tolerance window:** Stored as `batches.timestamp_tolerance_seconds` (default 2), configurable per batch via `POST /batches/upload`.

### 4.2 Edge Cases to Handle Explicitly
- **Multiple settlement records for one order** (partial settlements) → route to exception queue, don't force a 1:1 match.
- **Duplicate order IDs in the ledger** (rare but possible with retried orders) → route to exception queue rather than guessing.
- **Currency mismatch** → never auto-match across currencies; always route to exceptions.

---

## 5. LLM Discrepancy Reasoner (Step 2)

### 5.1 Input Construction
For each exception, build a context object:
```json
{
  "settlement_record": { "settled_amount": 1180.00, "gateway_txn_id": "...", "settlement_timestamp": "..." },
  "candidate_order": {
    "billed_amount": 1000.00,
    "order_id": "...",
    "is_international": true,
    "payment_method": "card",
    "refund_amount": null
  },
  "known_fee_schedule": { "domestic_mdr_pct": 2.0, "intl_mdr_pct": 3.0, "gst_pct": 18.0, "gateway_surcharge_flat": 10.0 }
}
```
For `ambiguous_multiple` cases, `candidate_order` becomes `candidate_orders: [...]` — an array of all plausible matches so the LLM can reason across them rather than rediscovering candidates from scratch.

### 5.2 Tool-Calling Requirement (Critical Design Decision)
The LLM **must not** perform arithmetic in free-text generation. It is given a callable tool:
```python
def calculate_difference(billed_amount: float, settled_amount: float,
                          fee_pct: float = 0, gst_on_fee_pct: float = 0,
                          flat_surcharge: float = 0,
                          refund_amount: float = 0,
                          fx_adjustment: float = 0) -> dict:
    fee = billed_amount * (fee_pct / 100)
    gst_on_fee = fee * (gst_on_fee_pct / 100)
    expected_settlement = billed_amount - fee - gst_on_fee - flat_surcharge - refund_amount + fx_adjustment
    return {
        "expected_settlement": round(expected_settlement, 2),
        "actual_settlement": settled_amount,
        "residual_gap": round(settled_amount - expected_settlement, 2)
    }
```
`refund_amount` and `fx_adjustment` are added to support combined-cause hypotheses (e.g., MDR + partial refund + FX rounding in one call) without requiring the LLM to sum partial results in free text.

The LLM's job is to **select which fee/tax/refund combination to test** (reasoning), then call the tool to verify the arithmetic (deterministic), then interpret whether the `residual_gap` is close enough to zero to confirm its hypothesis. If `residual_gap` exceeds a small tolerance after trying plausible combinations, the LLM must output `suggested_category: UNRESOLVED` rather than force-fitting an explanation.

**Server-side validation (applied after LLM responds, before writing to DB):**
```python
def validate_card(card: dict) -> dict:
    gap = abs(card["calculation_breakdown"]["residual_gap"])
    computed_confidence, computed_status = compute_confidence(gap)
    # Override LLM's self-reported values — compute_confidence is the single source of truth
    card["confidence_score"] = computed_confidence
    if computed_status != "resolved" and card["suggested_category"] != "UNRESOLVED":
        card["suggested_category"] = "UNRESOLVED"
        card["requires_human_review"] = True
    return card
```
This prevents a card with a non-trivial residual gap from being written as resolved regardless of what the LLM outputs.

### 5.3 Structured Output Schema (enforced via JSON mode / function-calling response format)
```json
{
  "hypothesis_text": "Shortfall matches 18% GST applied on a 3% international MDR fee, plus a flat ₹10 gateway surcharge.",
  "calculation_breakdown": {
    "billed_amount": 1000.00,
    "fee_pct_tested": 3.0,
    "gst_on_fee_pct_tested": 18.0,
    "flat_surcharge_tested": 10.0,
    "refund_amount_tested": 0.00,
    "fx_adjustment_tested": 0.00,
    "expected_settlement": 965.80,
    "actual_settlement": 965.80,
    "residual_gap": 0.00
  },
  "confidence_score": 0.94,
  "suggested_category": "MDR_VARIANCE",
  "requires_human_review": false
}
```
For unresolved cases:
```json
{
  "hypothesis_text": "No combination of known fee/tax/refund patterns explains a ₹212.40 gap. Recommend manual investigation.",
  "calculation_breakdown": { "residual_gap": 212.40, "attempts_tried": ["domestic_mdr", "intl_mdr", "partial_refund", "combined_mdr_refund"] },
  "confidence_score": 0.0,
  "suggested_category": "UNRESOLVED",
  "requires_human_review": true
}
```

### 5.4 Confidence Score — What It Actually Means
To avoid this being a decorative number: confidence is derived from `residual_gap` after the tool call, not asked for directly.
```
if residual_gap == 0:        confidence = 0.95–0.99  (exact match on a known pattern)
elif residual_gap <= 0.50:   confidence = 0.70–0.94  (close, minor rounding)
elif residual_gap <= 5.00:   confidence = 0.30–0.69  (plausible but not confirmed)
else:                        confidence = 0.0, category = UNRESOLVED
```
This makes the score defensible under questioning — it's a function of a verifiable number, not an LLM's self-assessment.

---

## 6. API Design (FastAPI)

| Endpoint | Method | Purpose |
|---|---|---|
| `/batches/upload` | POST | Upload settlement file + ledger file, creates a `batch`; accepts optional `timestamp_tolerance_seconds` param |
| `/batches/{batch_id}/run-matching` | POST | Triggers deterministic matching (Step 1); synchronous, returns on completion |
| `/batches/{batch_id}/run-reasoning` | POST | Sends exceptions to LLM reasoner (Step 2), async background job — returns `job_id` immediately |
| `/batches/{batch_id}/summary` | GET | Returns match-rate breakdown + pipeline `status` for the dashboard; frontend polls this after `run-reasoning` |
| `/batches/{batch_id}/exceptions` | GET | Returns all reasoning cards for review; supports `?limit=` and `?offset=` pagination |
| `/reconciliation/{result_id}/approve` | POST | Human approves → atomic `WHERE status='pending'` update → triggers journal posting; returns 409 if already actioned |
| `/reconciliation/{result_id}/reject` | POST | Human rejects → atomic `WHERE status='pending'` update → sets `human_rejected`, records `reviewed_by`; returns 409 if already actioned |
| `/batches/{batch_id}/audit-log` | GET | Returns immutable audit trail; supports `?event_type=` and `?from=`/`?to=` filter params |
| `/batches/{batch_id}/accuracy-report` | GET | Joins `reasoning_cards.suggested_category` against uploaded ground-truth answer key CSV; returns confusion matrix for demo accuracy claim |

**Async handling:** `run-reasoning` returns a job ID immediately; the frontend polls `/summary` for completion. `run-matching` is synchronous — the frontend should show a loading state and enable the "Run Reasoning" button only when `/summary` returns `status: matching_complete`.

**`/batches/{batch_id}/summary` response schema:**
```json
{
  "batch_id": "uuid",
  "status": "reasoning_complete",
  "total_records": 55,
  "matched_deterministic_count": 44,
  "matched_ai_resolved_count": 7,
  "unresolved_count": 3,
  "ingestion_error_count": 1,
  "match_rate_deterministic_pct": 80.0,
  "match_rate_ai_resolved_pct": 12.7,
  "throughput_ms": 8320
}
```

**Approve/reject idempotency rule (applies to both endpoints):** Both `/approve` and `/reject` use an atomic `UPDATE ... WHERE status = 'pending'` guard. If `rowcount == 0`, the card was already actioned by another request — return HTTP 409 Conflict. This covers double-clicks, concurrent accountants, and the cross-case race (approve + reject arriving simultaneously).

---

## 7. Sequence Diagram (Text Form)

```
User → Frontend: Upload settlement.csv + ledger.csv
Frontend → API: POST /batches/upload
API → Ingestion Service: parse + normalize
Ingestion Service → DB: insert settlement_records, order_ledger rows
Frontend → API: POST /batches/{id}/run-matching
API → Matching Engine: run deterministic pass
Matching Engine → DB: write reconciliation_results (matched_deterministic)
Matching Engine → Exception Queue: unmatched rows
Frontend → API: POST /batches/{id}/run-reasoning
API → LLM Reasoner (async): for each exception, build context → call LLM → call calculate_difference tool → parse structured output
LLM Reasoner → DB: write reasoning_cards + reconciliation_results (matched_ai_resolved or exception_unresolved)
Frontend → API: GET /batches/{id}/summary
API → Frontend: match rates, counts
Frontend → API: GET /batches/{id}/exceptions
API → Frontend: reasoning cards list
User → Frontend: clicks "Approve" on a card
Frontend → API: POST /reconciliation/{id}/approve
API → Audit Logger: log human_approval event
API → DB: mark journal entry as posted
```

---

## 8. Frontend Component Structure (React)

```
<ReconciliationDashboard>
  ├── <UploadPanel />                    -- file upload for settlement + ledger
  ├── <MatchRateSummaryCard />           -- 80% / 14% / 6% breakdown, throughput timer
  ├── <ExceptionList>
  │     └── <ReasoningCard>              -- one per exception
  │            ├── transaction_id, discrepancy amount
  │            ├── hypothesis_text
  │            ├── calculation_breakdown (expandable math table)
  │            ├── confidence_score (visual badge)
  │            └── <ApproveRejectButtons />
  └── <AuditLogViewer />                 -- searchable, read-only event stream
```

**Key UX detail:** the `calculation_breakdown` should render as an actual small table (billed amount, fee %, GST %, expected vs. actual) rather than just displaying the LLM's prose — this is what makes the "reasoning card" concept land with judges as verifiable, not just a confident-sounding paragraph.

---

## 9. Evaluation / Synthetic Dataset Design

Build a batch of 50–60 records with a deliberate, documented mix:
- **~40 records (80%):** Clean 1:1 matches, no discrepancy.
- **~7 records (14%):** Genuine but explainable discrepancies — vary the cause across: domestic MDR, international MDR, GST-on-fee, partial refund, flat gateway surcharge, and at least one *combination* of two causes (to stress-test the reasoner).
- **~3 records (6%):** Deliberately unresolvable — a discrepancy that matches no known fee pattern (e.g., a data-entry error in your synthetic file), so the system is forced to honestly output `UNRESOLVED` rather than force-fit an explanation.

**Ground truth file:** keep a separate, hidden answer key (`category`, `true_cause`) for each of the ~10 non-trivial records, generated *before* you build the reasoner — this is what lets you report actual accuracy ("7 of 7 explainable discrepancies correctly categorized") rather than just showing plausible-sounding output.

---

## 10. Error Handling

| Failure Mode | Handling |
|---|---|
| Malformed CSV row | Log to `audit_log` as `ingestion_error`, skip row, surface count in summary |
| LLM API timeout/failure | Retry once; on second failure, mark record as `exception_unresolved` with `hypothesis_text: "LLM reasoning unavailable — manual review required"` — never leave a record silently unprocessed |
| Tool call returns implausible result (e.g., negative fee) | Discard that hypothesis attempt, try next candidate fee combination, or fall through to `UNRESOLVED` |
| Duplicate batch upload | Warn and require explicit confirmation before overwriting |

---

## 11. Non-Functional Notes

- **Throughput target:** deterministic matching pass should be near-instant (<1s for 50 records, it's just DB comparisons). LLM reasoning pass on ~10 exception records is the real latency budget — parallelize these calls (async batch, not sequential) to keep total reasoning time under ~10–15 seconds for the demo.
- **Idempotency:** re-running `run-matching` on the same batch will not create duplicate `reconciliation_results` rows — enforced by `UNIQUE(batch_id, settlement_record_id)` constraint on the table, not just application logic.
- **Security (even for a hackathon):** don't log raw file contents containing PII beyond what's needed; the `raw_row_json` fields are fine for a synthetic demo dataset but note this as a production consideration if asked.

---

## 12. Build Order (Suggested Sequence)

1. DB schema + ingestion endpoint (CSV parsing) — get real data flowing first.
2. Deterministic matching engine — this alone gets you a working 80% demo.
3. Synthetic dataset with documented ground truth — build this in parallel with step 2.
4. LLM reasoner with tool-calling for arithmetic — the highest-risk component, start early.
5. Reasoning card structured output + confidence scoring logic.
6. Dashboard UI (summary card, exception list, approve/reject).
7. Audit log viewer — often last, but keep the underlying `audit_log` writes happening from step 1 onward so you're not retrofitting logging at the end.

This ordering front-loads the two highest-risk items (LLM tool-calling reliability and honest synthetic data) rather than leaving them for the final hours.
