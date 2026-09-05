# Technical Design Document
## Multi-Source Settlement Reconciler

---

## 1. System Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  React Frontend                                                   │
│  UploadPanel → Pipeline Stepper → SummaryCard → ExceptionList    │
└────────────────────────┬─────────────────────────────────────────┘
                         │ HTTP (REST)
┌────────────────────────▼─────────────────────────────────────────┐
│  FastAPI Backend                                                  │
│  ┌──────────────┐  ┌─────────────────┐  ┌────────────────────┐  │
│  │ Ingestion    │  │ Matching Engine │  │ LLM Reasoner       │  │
│  │ Service      │  │ (Deterministic) │  │ (Async, Parallel)  │  │
│  └──────┬───────┘  └────────┬────────┘  └─────────┬──────────┘  │
│         │                   │                     │              │
│  ┌──────▼───────────────────▼─────────────────────▼──────────┐  │
│  │  Audit Logger (writes on every event)                      │  │
│  └────────────────────────────────────────────────────────────┘  │
└───────────────────────────────┬──────────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────────┐
│  PostgreSQL Database                                              │
│  batches | settlement_records | order_ledger |                   │
│  reconciliation_results | exception_candidates |                 │
│  reasoning_cards | audit_log                                     │
└──────────────────────────────────────────────────────────────────┘
                                │
                   ┌────────────▼────────────┐
                   │  LLM API (OpenAI/Claude) │
                   │  + calculate_difference  │
                   │    tool (server-side)    │
                   └─────────────────────────┘
```

---

## 2. Key Design Decisions

### 2.1 Deterministic-First, AI-Second

80% of records are matched without any LLM involvement. AI is used only where rules cannot resolve the discrepancy. This:
- Keeps costs low (fewer LLM calls)
- Keeps the system fast (deterministic matching is near-instant)
- Makes the AI's role explainable ("here are the 11 records the rules couldn't resolve")

### 2.2 Tool-Calling for Arithmetic Integrity

The LLM cannot do financial arithmetic in free text. It is given exactly one tool: `calculate_difference`. The LLM selects the hypothesis (which fee parameters to test); the tool computes the result; the server validates consistency.

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

### 2.3 Server-Side Confidence Override

The LLM is not trusted to report its own confidence score. After every LLM response, `validate_card()` overwrites both `confidence_score` and `suggested_category` with values derived from `compute_confidence(residual_gap)`.

```python
def validate_card(card: dict) -> dict:
    gap = abs(card["calculation_breakdown"]["residual_gap"])
    computed_confidence, computed_status = compute_confidence(gap)
    card["confidence_score"] = computed_confidence
    if computed_status != "resolved" and card["suggested_category"] != "UNRESOLVED":
        card["suggested_category"] = "UNRESOLVED"
        card["requires_human_review"] = True
    return card
```

### 2.4 Separated Order_ID vs Fallback Confirmation Logic

The matching algorithm uses different confirmation logic for the two paths:
- **Order_id path**: trust the match unconditionally; use fee sanity check as optional flag only when `fee_deducted` is present
- **Fallback path**: amount-based filter already runs as the query condition; confirmation is implicit

This prevents the bug where a valid order_id match gets rejected simply because `fee_deducted` is absent from the settlement file.

### 2.5 Human Approval as a Hard Gate

No data is posted to the ledger without explicit human approval. The API uses an atomic conditional update on both approve and reject:

```sql
UPDATE reconciliation_results
SET status = 'human_approved', reviewed_at = NOW(), reviewed_by = :user_id
WHERE id = :result_id AND status = 'pending'
```

If `rowcount == 0`, return 409. This prevents duplicate journal entries from double-clicks or concurrent approvals.

---

## 3. Matching Algorithm (Pseudocode)

```python
for record in batch.settlement_records:
    # Primary: order_id match
    if record.order_id:
        candidates = query_ledger_by_order_id(record.order_id)
    else:
        candidates = []

    # Fallback: fee-adjusted amount + timestamp
    if not candidates and record.fee_deducted is not None:
        candidates = query_ledger_by_amount_and_time(
            expected_settled = record.billed_amount - record.fee_deducted,
            actual_settled   = record.settled_amount,
            tolerance_amount = 0.01,
            settlement_ts    = record.settlement_timestamp,
            tolerance_secs   = batch.timestamp_tolerance_seconds
        )

    # Confirm
    if len(candidates) == 1 and came_from_order_id_path:
        if record.fee_deducted:
            sanity = abs(candidates[0].billed_amount - record.fee_deducted - record.settled_amount)
            if sanity >= 0.01:
                route_to_exception(record, candidates[0], reason='amount_mismatch')
                continue
        match(record, candidates[0], reason='order_id_match')

    elif len(candidates) == 1 and came_from_fallback_path:
        match(record, candidates[0], reason='amount_match')

    elif len(candidates) > 1:
        route_to_exception(record, candidates, reason='ambiguous_multiple')

    elif currency_mismatch(record, candidates):
        route_to_exception(record, None, reason='currency_mismatch')

    else:
        route_to_exception(record, None, reason='no_match')
```

---

## 4. LLM Reasoning Flow

```
For each exception in parallel (LangChain .batch()):

1. Build context:
   {
     settlement_record: { settled_amount, gateway_txn_id, settlement_timestamp },
     candidate_order: { billed_amount, order_id, is_international, payment_method, refund_amount }
         OR candidate_orders: [...] for ambiguous_multiple,
     known_fee_schedule: { domestic_mdr_pct, intl_mdr_pct, gst_pct, gateway_surcharge_flat },
     routing_reason: "amount_mismatch"
   }

2. LLM prompt instructs:
   - Select the most likely fee/refund hypothesis
   - Call calculate_difference with chosen parameters
   - If residual_gap > tolerance, try next hypothesis
   - After N attempts, output UNRESOLVED

3. Tool call executes server-side: returns expected_settlement, residual_gap

4. LLM interprets residual_gap, outputs structured JSON

5. validate_card() overrides confidence and category

6. Write reasoning_card + reconciliation_result to DB

7. Log llm_call event to audit_log
```

---

## 5. API Contract Summary

| Endpoint | Method | Sync/Async | Auth |
|---|---|---|---|
| `/batches/upload` | POST | Sync | None (demo) |
| `/batches/{id}/run-matching` | POST | Sync | None |
| `/batches/{id}/run-reasoning` | POST | Async (job_id) | None |
| `/batches/{id}/summary` | GET | Sync | None |
| `/batches/{id}/exceptions` | GET | Sync | None |
| `/reconciliation/{id}/approve` | POST | Sync | None |
| `/reconciliation/{id}/reject` | POST | Sync | None |
| `/batches/{id}/audit-log` | GET | Sync | None |
| `/batches/{id}/accuracy-report` | GET | Sync | None |

---

## 6. Failure Handling

| Failure | Handling |
|---|---|
| Malformed CSV row | Skip, log `ingestion_error`, increment counter |
| LLM timeout | Retry once; fallback to UNRESOLVED |
| Tool call returns negative fee | Discard hypothesis, try next |
| Duplicate batch | 409, require confirm |
| Double approve/reject | 409, idempotent |
| DB write failure | Rollback transaction, surface error in summary |
