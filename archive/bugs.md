# bugs.md
## Known Issues, Resolved Bugs, and Watch Items
## Multi-Source Settlement Reconciler

---

## Format

Each entry:
- **Status**: RESOLVED | OPEN | WATCH
- **Severity**: P0 (blocks demo) | P1 (degrades accuracy) | P2 (edge case) | P3 (cosmetic)
- **Discovered**: how/when found
- **Root cause**: what went wrong
- **Fix**: what was changed

---

## RESOLVED

### BUG-001 — Fallback match compares billed_amount to settled_amount directly
- **Status**: RESOLVED
- **Severity**: P0
- **Discovered**: Design review pass 1
- **Root cause**: Original pseudocode compared `abs(billed_amount - settled_amount) < 0.01`. These two amounts are never equal — settled is always billed minus fees. The fallback returned zero matches on any fee-deducted record.
- **Fix**: Changed fallback to compare `abs((billed_amount - fee_deducted) - settled_amount) < 0.01`. Fallback only runs when `fee_deducted IS NOT NULL`.

---

### BUG-002 — Order_id confirmation step shared same broken amount check as fallback
- **Status**: RESOLVED
- **Severity**: P0
- **Discovered**: Design review pass 2 (after BUG-001 fix)
- **Root cause**: The fix for BUG-001 introduced a shared confirmation line: `abs(billed - fee_deducted - settled) < 0.01` used by both paths. If `fee_deducted` is null for an order_id match (common — many settlement files don't break out fee per line), the arithmetic involves NULL and the comparison fails. Valid order_id matches get routed to exceptions.
- **Fix**: Separated confirmation logic by path. Order_id path: accept match unconditionally; use fee sanity check as optional flag only when `fee_deducted` is present, not as a gate. Fallback path: implicit confirmation (filter already ran on amount).

---

### BUG-003 — Concurrent approve/reject can produce duplicate journal entries
- **Status**: RESOLVED
- **Severity**: P0
- **Discovered**: Design review — concurrency analysis
- **Root cause**: Both approve and reject endpoints read status, then write. Two simultaneous clicks both read "pending," both execute logic.
- **Fix**: Atomic conditional update on both endpoints: `UPDATE ... WHERE id = :id AND status = 'pending'`. If rowcount == 0, return 409.

---

### BUG-004 — Reject path had no valid status ENUM value
- **Status**: RESOLVED
- **Severity**: P0
- **Discovered**: Design review — schema analysis
- **Root cause**: `reconciliation_results.status` ENUM only had `matched_deterministic`, `matched_ai_resolved`, `exception_unresolved`. No `human_rejected` state existed.
- **Fix**: Added `human_approved` and `human_rejected` to the status ENUM. Added `reviewed_at`, `reviewed_by` columns.

---

### BUG-005 — `validate_card()` referenced undefined `RESOLVED_THRESHOLD` constant
- **Status**: RESOLVED
- **Severity**: P1
- **Discovered**: Code review of generated snippet
- **Root cause**: Original snippet checked `if gap > RESOLVED_THRESHOLD` — constant never defined anywhere.
- **Fix**: Changed to `if computed_status != "resolved"` — derives the check from `compute_confidence()` directly. No separate constant needed.

---

### BUG-006 — `calculate_difference` signature couldn't express combined-cause hypotheses
- **Status**: RESOLVED
- **Severity**: P1
- **Discovered**: Design review — tool signature analysis
- **Root cause**: Tool only accepted `fee_pct` and `flat_surcharge`. Combined causes (MDR + refund + FX) required multiple calls and free-text summing.
- **Fix**: Added `refund_amount: float = 0` and `fx_adjustment: float = 0` parameters.

---

### BUG-007 — Timestamp fallback tolerance (±2s) contradicts T+2 settlement cycle
- **Status**: RESOLVED (decision made)
- **Severity**: P0
- **Discovered**: Design review pass 2
- **Root cause**: ±2 seconds only makes sense if `settlement_timestamp` is the original transaction timestamp. If it's the T+2 credit-posting time, no Monday order would ever be within 2 seconds of a Wednesday settlement.
- **Fix**: Decision documented — `settlement_timestamp` is assumed to be the original transaction timestamp echoed back by the gateway (consistent with real Razorpay settlement file format). This is stated explicitly in §3.1 and §4.1 of the LLD.

---

### BUG-008 — No UNIQUE constraint on `(batch_id, gateway_txn_id)`
- **Status**: RESOLVED
- **Severity**: P1
- **Discovered**: Schema review
- **Root cause**: A CSV with a repeated row would insert two identical settlement records, both matching the same ledger entry, producing two reconciliation_results rows.
- **Fix**: Added `UNIQUE(batch_id, gateway_txn_id)` constraint to `settlement_records`.

---

### BUG-009 — Idempotency guarantee was code-level promise only
- **Status**: RESOLVED
- **Severity**: P1
- **Discovered**: Schema review
- **Root cause**: The LLD stated "key on (batch_id, settlement_record_id)" for idempotency, but no DB constraint existed.
- **Fix**: Added `UNIQUE(batch_id, settlement_record_id)` constraint to `reconciliation_results`.

---

### BUG-010 — `payment_method` missing from LLM context object
- **Status**: RESOLVED
- **Severity**: P2
- **Discovered**: Review of §5.1 context example
- **Root cause**: `payment_method` column was added to `order_ledger` schema but not included in the context JSON passed to the LLM. Fee rate selection by the LLM had no signal for card vs UPI vs netbanking.
- **Fix**: Added `"payment_method": "card"` to `candidate_order` in the §5.1 context example and noted it must be populated in the context builder.

---

### BUG-011 — Ambiguous-multiple routing had no storage for multiple candidates
- **Status**: RESOLVED (schema)
- **Severity**: P2
- **Discovered**: Schema analysis — `order_ledger_id` is a single FK
- **Root cause**: `reconciliation_results.order_ledger_id` can only hold one candidate. For `ambiguous_multiple` routing, all candidate order_ledger_ids were lost.
- **Fix**: Added `exception_candidates(reconciliation_result_id, order_ledger_id)` join table. LLM context for ambiguous_multiple cases uses `candidate_orders: [...]` array.

---

## OPEN

None currently. All identified design bugs have been resolved in the LLD and schema.

---

## WATCH ITEMS (not bugs yet, but monitor during build)

### WATCH-001 — Confidence threshold ₹5.00 not yet calibrated against real data
- The upper band threshold (₹5.00) was chosen by reasoning, not by observing actual residual gaps from the synthetic dataset.
- **Action**: After building Phase 3 (synthetic dataset), run all 7 explainable discrepancy records through `calculate_difference` with the correct hypothesis. Note the largest residual gap among correct explanations. Set the threshold just above that value.

### WATCH-002 — LLM may report `fee_pct=0.03` instead of `fee_pct=3.0`
- LLMs are known to confuse percentage (3.0) with decimal (0.03) when calling tools.
- **Action**: Add input validation to `calculate_difference`: if `fee_pct < 0.5`, log a warning and consider rejecting the call as likely a decimal/percentage confusion. Or normalize in the tool itself.

### WATCH-003 — LLM may not call the tool at all on some records
- Some LLM providers occasionally skip tool calls and return free-text reasoning instead.
- **Action**: After receiving LLM response, check if a tool call was made. If not, retry once. On second failure, route to UNRESOLVED with note "LLM did not use required tool."

### WATCH-004 — Demo API latency under conference WiFi
- LLM reasoning on 10 records in parallel can hit 30–45s on high-latency connections.
- **Action**: Pre-compute the synthetic dataset's reasoning_cards and cache in DB before the demo. Show live upload → matching live; reveal pre-cached cards as "reasoning complete."
