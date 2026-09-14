# Track 4 Reconciler — Review Findings & Action Items

---

## ✅ WHAT'S GOOD (keep as-is)

- **Confidence score derived from `residual_gap`, not LLM self-reporting** — fully defensible under judge questioning.
- **Human approval gate (Stage 6)** — correct architectural decision, directly satisfies the track bar's "honest exception list" requirement.
- **LLM + tool-calling split** — LLM selects fee hypothesis, deterministic tool verifies arithmetic. Right separation of concerns.
- **Immutable audit log from day 1** — logging every match, LLM call, and human decision from the start rather than retrofitting is the right call.
- **Ground-truth answer key generated before building the reasoner** — ensures accuracy is reported against known answers, not post-hoc rationalization.
- **Exception routing without forced 1:1 matching** — correctly refuses to guess when ambiguous.
- **Build order (§12)** — front-loads the two highest-risk items (LLM tool-calling + synthetic data) rather than leaving them for the final hours. Follow this.
- **Framing "6% unresolved" as honesty, not failure** — correct pitch instinct.
- **PostgreSQL for financial data** — ACID guarantees are appropriate here. Good call.
- **Async background task for `run-reasoning`** — right pattern to avoid blocking the UI during LLM calls.

---

## ❌ WHAT'S BROKEN (must fix before building)

### 1. Fallback match condition is logically wrong
**Location:** §4.1 matching algorithm pseudocode

**Problem:** The fallback compares `billed_amount` to `settled_amount` directly with a ±₹0.01 tolerance. These two amounts are never equal — `settled_amount` is always `billed_amount` minus fees. A ₹1000 order settled at ₹976.40 has a ₹23.60 difference. The fallback will match zero records on any fee-deducted order, silently routing them all to exceptions and destroying your 80% match rate demo number.

**Fix:** Change the fallback to compare `billed_amount - fee_deducted` vs `settled_amount` (only when `fee_deducted` is present in the settlement file), OR accept that the fallback only covers zero-fee edge cases and document that honestly. The primary path (order_id match) needs to carry the load.

---

### 2. `calculate_difference` tool signature can't express combined-cause hypotheses
**Location:** §5.2 tool definition

**Problem:** The tool takes a single `fee_pct` and a single `flat_surcharge`. Your synthetic dataset includes at least one "combined cause" record (e.g., MDR + partial refund + FX rounding together). There's no way to express this in one tool call. The LLM would have to call the tool multiple times and sum residuals in free text — which is exactly the free-text arithmetic problem the tool was designed to prevent.

**Fix:** Add `refund_amount: float = 0` and `fx_adjustment: float = 0` parameters to `calculate_difference`. Update the structured output schema and the `calculation_breakdown` JSONB to include these fields.

```python
def calculate_difference(billed_amount, settled_amount,
                          fee_pct=0, gst_on_fee_pct=0,
                          flat_surcharge=0, refund_amount=0,
                          fx_adjustment=0) -> dict:
    fee = billed_amount * (fee_pct / 100)
    gst_on_fee = fee * (gst_on_fee_pct / 100)
    expected = billed_amount - fee - gst_on_fee - flat_surcharge - refund_amount + fx_adjustment
    return {
        "expected_settlement": round(expected, 2),
        "actual_settlement": settled_amount,
        "residual_gap": round(settled_amount - expected, 2)
    }
```

---

### 3. Concurrent approval/rejection clicks → duplicate journal entries or split-brain state
**Location:** §6 API, `POST /reconciliation/{result_id}/approve` and `POST /reconciliation/{result_id}/reject`

**Problem:** Two simultaneous clicks (or two accountants) on Approve for the same card both read status as "pending," both execute approval logic, both write journal entries. No guard exists. The same race applies to `/reject` — and the cross-case race (approve + reject firing simultaneously on the same card) is also unhandled.

**Fix:** Apply the identical atomic conditional-update pattern to **both** endpoints. This is one shared idempotency rule, not two separate ones.

```sql
-- /approve
UPDATE reconciliation_results
SET status = 'human_approved', reviewed_at = NOW(), reviewed_by = :user_id
WHERE id = :result_id AND status = 'pending'

-- /reject
UPDATE reconciliation_results
SET status = 'human_rejected', reviewed_at = NOW(), reviewed_by = :user_id
WHERE id = :result_id AND status = 'pending'
```

If `rowcount == 0` for either endpoint, return HTTP 409 Conflict regardless of which action arrived second. Do not re-execute journal posting.

---

### 4. Reject path is a dead end
**Location:** §6 API, `POST /reconciliation/{result_id}/reject`; §3.3 `reconciliation_results` ENUM

**Problem (a):** The `reconciliation_results.status` ENUM only has `matched_deterministic`, `matched_ai_resolved`, `exception_unresolved`. None of these cover "human rejected." After rejection, the row has no valid status to transition to.

**Problem (b):** The API says "flags for manual handling" with no further definition. There's no dashboard state change after rejection, no `rejected_at` timestamp, no re-queue path.

**Fix:**
- Add `human_approved` and `human_rejected` to the `reconciliation_results.status` ENUM.
- Add `reviewed_at TIMESTAMP` and `reviewed_by VARCHAR` columns to `reconciliation_results`.
- Add `human_override_note TEXT` to `reasoning_cards` (optional, for the human to record why they rejected).
- Dashboard: rejected cards should render visually distinct from pending and approved ones.

---

### 5. No server-side guard on LLM output consistency
**Location:** §5 LLM Reasoner — missing validation layer

**Problem:** The LLM can return a card where `residual_gap` is ₹3.40 but `suggested_category` is `MDR_VARIANCE` and `confidence_score` is 0.65. The confidence formula would produce ~0.52 for a ₹3.40 gap, but the LLM might self-report something different. More critically, a card with a non-trivial residual gap should not be written as "resolved."

**Fix:** After receiving the LLM's structured output, run a server-side validation before writing to DB. Use `computed_status` from `compute_confidence` as the single source of truth — do not introduce a separate `RESOLVED_THRESHOLD` constant that can drift out of sync with the confidence formula.

```python
def validate_card(card: dict) -> dict:
    gap = abs(card["calculation_breakdown"]["residual_gap"])
    computed_confidence, computed_status = compute_confidence(gap)
    # Override LLM's self-reported values with computed ones
    card["confidence_score"] = computed_confidence
    if computed_status != "resolved" and card["suggested_category"] != "UNRESOLVED":
        card["suggested_category"] = "UNRESOLVED"
        card["requires_human_review"] = True
    return card
```

`compute_confidence` already encodes the band boundaries (≤₹0.50 = resolved, ≤₹5.00 = low_confidence, else unresolved). Deriving the check from `computed_status` means there's one place to update if thresholds are recalibrated.

---

### 16. Timestamp fallback tolerance contradicts the T+2 settlement cycle
**Location:** §4.1 matching algorithm, tolerance window note — shares root cause with item 1, fix together

**Problem:** The fallback match compares `order_timestamp` to `settlement_timestamp` with a ±2 second tolerance. But the project's own problem framing states settlements land on a T+2 (2 business day) cycle. An order placed Monday and settled Wednesday will never be within 2 seconds of its own order timestamp. Even after fixing the amount-comparison bug (item 1), the timestamp gate will still eliminate virtually all fallback candidates before they're evaluated on amount. The two bugs share the same root cause: the fallback doesn't reflect how real settlement data is structured.

**Fix — pick one and document the choice explicitly in §4.1:**
- If `settlement_timestamp` is the original transaction timestamp echoed back in the settlement file (common in real gateway reports), a ±2 second window makes sense — but the field name and description should say so explicitly.
- If `settlement_timestamp` is the credit-posting time (T+2 batch timestamp), widen the tolerance window to reflect the settlement cycle, or drop timestamp from the fallback entirely and rely on `order_id` + amount only.

Whichever you choose, add one sentence to §4.1 stating the assumption so a judge question doesn't surface it live.

---

### 17. Concurrency guard on `/reject` missing (asymmetric with `/approve`)
**Location:** §6 API, `POST /reconciliation/{result_id}/reject` — see also item 3

**Problem:** The addendum to item 3 makes this explicit: the same race condition that exists on `/approve` also exists on `/reject`, and there's no handling for the cross-case race (approve + reject arriving simultaneously). The fix in item 3 above already incorporates this — this item exists as a standalone tracking entry so it doesn't get missed when working from the priority table.

**Fix:** Covered by item 3's fix. Apply the `WHERE status = 'pending'` atomic guard to `/reject` identically to `/approve`. Return 409 if `rowcount == 0` on either path.

---

## ⚠️ WHAT NEEDS TO BE ADDED (gaps, not errors)

### 6. `batches` table has no pipeline status field
**Location:** §3.6 schema

**Problem:** The frontend has no reliable way to know if a batch is in `uploaded`, `matching_complete`, or `reasoning_complete` state. The summary endpoint returns null `match_rate_ai_resolved` both when reasoning hasn't run yet and when it found zero AI matches.

**Fix:** Add `status ENUM('uploaded', 'matching_complete', 'reasoning_complete', 'failed')` to the `batches` table. Drive the dashboard's "Run Matching" / "Run Reasoning" button states from this field.

---

### 7. Missing UNIQUE constraints in schema
**Location:** §3.1 `settlement_records`, §3.3 `reconciliation_results`

**Missing:**
- `UNIQUE(batch_id, gateway_txn_id)` on `settlement_records` — prevents duplicate rows from a CSV with repeated transactions.
- `UNIQUE(batch_id, settlement_record_id)` on `reconciliation_results` — enforces the idempotency guarantee you stated in §11 but didn't put in the schema.

---

### 8. `reconciliation_results` can have both FKs null
**Location:** §3.3 schema

**Problem:** Both `settlement_record_id` and `order_ledger_id` are nullable. No constraint prevents a row where both are null — an orphaned result row with no parent records.

**Fix:** Add: `CHECK (settlement_record_id IS NOT NULL OR order_ledger_id IS NOT NULL)`

Better: make `settlement_record_id` NOT NULL always (you're always reconciling from a settlement record) and keep only `order_ledger_id` nullable.

---

### 9. Exception queue entries don't carry the candidate match signal
**Location:** §4.1 algorithm

**Problem:** When `order_id` matches but `amount` doesn't (the most common discrepancy case), the record routes to the exception queue but the `order_ledger_id` of the matched order is not passed through. The LLM has to rediscover this link from scratch via the context object.

**Fix:** When routing to exceptions, populate `reconciliation_results.order_ledger_id` with the candidate match even though it's not confirmed. Add a `match_confidence` field or a `routing_reason ENUM('no_match', 'amount_mismatch', 'ambiguous_multiple', 'currency_mismatch')` so the LLM context includes why the record is an exception.

---

### 10. No `payment_method` on `order_ledger`
**Location:** §3.2 schema

**Problem:** Fee rates differ by payment method (card vs UPI vs netbanking). The schema has `is_international BOOLEAN` but nothing for payment method. When a judge asks how it determines which MDR rate applies, you have nothing to show.

**Fix (minimal):** Add `payment_method VARCHAR` to `order_ledger`. Populate it in synthetic data. Pass it in the LLM context object. Even if the fee schedule only has two rates (domestic/international), the field makes the demo more realistic.

---

### 11. `audit_log.event_type` is VARCHAR, not ENUM
**Location:** §3.5 schema

**Problem:** Inconsistent string values from different code paths will silently break the audit log viewer's filter and the frontend's event type display.

**Fix:** Change to `event_type ENUM('ingestion_error', 'match', 'llm_call', 'human_approval', 'human_rejection', 'journal_posted')`. Add new values explicitly as you add features.

---

### 12. `GET /batches/{batch_id}/summary` response schema undefined
**Location:** §6 API

**Problem:** This is the endpoint the frontend polls for reasoning completion status. Without a defined response shape, `<MatchRateSummaryCard />` can't be built independently.

**Suggested response schema:**
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

---

### 13. No `ingestion_error_count` in batch summary
**Location:** §3.6 `batches` schema + §6 summary endpoint

**Problem:** Error handling says malformed CSV rows are skipped and logged. But the batch summary has no field to surface this count. A judge who uploads a slightly malformed CSV will see a lower-than-expected record count with no explanation.

**Fix:** Add `ingestion_error_count INT DEFAULT 0` to the `batches` table and include it in the summary response.

---

### 14. Timestamp tolerance window is "configurable" but has nowhere to live — and ±2 seconds may be the wrong value entirely
**Location:** §4.1 algorithm notes — see also item 16

**Problem (a):** Described as "configurable per batch" but there's no column in `batches`, no field in the upload request body, and no API parameter for it.

**Problem (b):** More importantly, ±2 seconds may be fundamentally wrong depending on what `settlement_timestamp` actually represents — see item 16. Fixing the config-storage problem while leaving the underlying value wrong means you've done work that doesn't matter.

**Fix:** Resolve item 16 first (decide what `settlement_timestamp` means and what tolerance makes sense). Then either add `timestamp_tolerance_seconds INT DEFAULT 2` to `batches` and expose it as an optional param in `POST /batches/upload`, OR remove the word "configurable" and treat it as a system constant. Add one sentence to §4.1 documenting the assumption.

---

### 15. No accuracy comparison script
**Location:** §9 evaluation design

**Problem:** You have a hidden ground-truth answer key, but no described mechanism for comparing it against `reasoning_cards.suggested_category` at demo time. Without a runnable comparison, the accuracy claim ("7 of 7 correctly categorized") is a manual eyeball, not a verifiable result.

**Fix:** Write a small Python script (or a `/batches/{batch_id}/accuracy-report` endpoint) that joins `reasoning_cards` against the answer key CSV and prints a confusion matrix. This is what you show when a judge asks "prove it."

---

## 🔧 NICE TO HAVE (low priority, do if time allows)

- Add `limit`/`offset` pagination to `GET /batches/{batch_id}/exceptions` and `GET /batches/{batch_id}/audit-log`.
- Add `?event_type=` and `?from=`/`?to=` filter params to the audit log endpoint.
- Add composite index `(batch_id, timestamp)` on `audit_log` for query performance.
- Add `reasoning_cards.batch_id` as a denormalized column to avoid the two-hop join on the exceptions endpoint.
- Add `POST /reconciliation/{result_id}/requeue` for rejected cards (or at minimum a `human_override_note` field on the card).
- Multi-hypothesis retry loop (LangGraph) — strongest demo enhancement if time allows.
- Negative residual gap handling: distinguish "settled less than expected" (fee issue) from "settled more than expected" (potential duplicate payment) in the dashboard rendering.

---

## 📋 PRIORITY ORDER FOR FIXES

**Consolidated P0 list (updated from addendum):**
- Fix fallback match condition + timestamp tolerance together (items 1 + 16) — 45–60 min combined
- Add concurrency guard to both `/approve` and `/reject` (items 3 + 17) — 30 min combined
- Fix reject path ENUM + status (item 4) — 30 min

| Priority | Item | Effort | Risk if skipped |
|---|---|---|---|
| P0 | Fix fallback match condition (item 1) + timestamp tolerance vs. T+2 cycle (item 16) — fix together | 45–60 min | Fallback returns ~0 matches on amount AND timestamp; 80% match rate demo breaks |
| P0 | Add concurrency guard to both `/approve` and `/reject` (items 3 + 17) | 30 min | Duplicate journal entries on double-click; race condition on reject path |
| P0 | Fix reject path ENUM + status (item 4) | 30 min | Rejection breaks DB state |
| P1 | Extend `calculate_difference` for combined causes (item 2) | 45 min | Combined-cause test records fail to resolve |
| P1 | Add server-side card validation with `compute_confidence`-derived status check (item 5) | 30 min | LLM output inconsistency reaches dashboard |
| P1 | Add `batches.status` ENUM (item 6) | 20 min | Frontend can't drive pipeline stage buttons |
| P1 | Add UNIQUE constraints to schema (item 7) | 15 min | Silent duplicate rows in DB |
| P2 | Add CHECK constraint / NOT NULL on `reconciliation_results` FKs (item 8) | 10–15 min | Orphaned result rows with no parent record possible |
| P2 | Add `routing_reason` to exception entries (item 9) | 30 min | LLM loses match signal context |
| P2 | Define summary endpoint response schema (item 12) | 20 min | Frontend can't be built independently |
| P2 | Add `ingestion_error_count` to batches (item 13) | 15 min | Unexplained record count discrepancies |
| P2 | Write accuracy comparison script (item 15) | 45 min | Accuracy claim is unverifiable live |
| P1–P2 | Fix timestamp tolerance ownership — resolve item 16 first, then decide storage (item 14) | 15 min | Was P3; re-filed — cosmetic fix is pointless if tolerance value is wrong |
| P3 | Add `payment_method` to order_ledger (item 10) | 20 min | Weak answer to judge question on MDR rates |
| P3 | Change `event_type` to ENUM (item 11) | 10 min | Audit log filter silently breaks |
