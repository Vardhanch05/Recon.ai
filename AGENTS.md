# AGENTS.md — AI Context File
## Multi-Source Settlement Reconciler

This file provides context for AI coding assistants (Claude, GPT-4o, Cursor, etc.) working on this codebase. Read this before writing any code.

---

## What This System Does

A settlement reconciliation agent for Razorpay merchants. It:
1. Ingests a Razorpay settlement CSV + merchant order ledger CSV
2. Deterministically matches ~80% of records (no AI)
3. Uses an LLM to explain the remaining ~14% of discrepancies (fee/refund reasoning)
4. Flags ~6% as genuinely unresolvable
5. Surfaces reasoning cards for human approval before any ledger posting

---

## Architecture in One Paragraph

FastAPI backend, PostgreSQL, React frontend. The pipeline is: CSV upload → ingestion → deterministic matching → exception routing → LLM reasoning (async, parallel) → reasoning cards → human approval → journal posting. Every event is logged to an immutable audit_log. The LLM uses a tool call (`calculate_difference`) for all arithmetic — never free-text math.

---

## Finalized Decisions — Do Not Redesign

These are decided and stable:

- **Confidence score**: computed from `residual_gap` via `compute_confidence()`. Never LLM self-reported. `validate_card()` overrides any LLM output before DB write.
- **Tool-calling**: LLM must call `calculate_difference` to verify arithmetic. If it returns free-text math, reject and retry.
- **No LangGraph for core loop**: plain LangChain `.batch()` for parallelism. LangGraph only if building a multi-hypothesis retry loop (optional enhancement).
- **Human approval is a hard gate**: nothing posts to ledger without explicit approve. Atomic `WHERE status='pending'` guard on both approve and reject endpoints.
- **Order_id path uses unconditional trust**: if order_id matches, accept it — don't gate on `fee_deducted` being present. Fee sanity check is optional flag only.
- **PostgreSQL**: ACID required for financial data. No NoSQL.

---

## Critical Functions

### `compute_confidence(residual_gap: float) -> tuple[float, str]`
```python
def compute_confidence(residual_gap: float) -> tuple[float, str]:
    gap = abs(residual_gap)
    if gap <= 0.05:
        return round(0.99 - (gap / 0.05) * 0.04, 2), "resolved"
    elif gap <= 0.50:
        return round(0.94 - ((gap - 0.05) / 0.45) * 0.24, 2), "resolved"
    elif gap <= 5.00:
        return round(0.69 - ((gap - 0.50) / 4.50) * 0.39, 2), "low_confidence"
    else:
        return 0.0, "unresolved"
```
This is the single source of truth for confidence. Do not add a separate threshold constant elsewhere.

### `validate_card(card: dict) -> dict`
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
Always call this after receiving LLM output, before writing to DB.

### `calculate_difference` (LLM tool)
```python
def calculate_difference(billed_amount: float, settled_amount: float,
                          fee_pct: float = 0, gst_on_fee_pct: float = 0,
                          flat_surcharge: float = 0,
                          refund_amount: float = 0,
                          fx_adjustment: float = 0) -> dict:
    fee = billed_amount * (fee_pct / 100)
    gst_on_fee = fee * (gst_on_fee_pct / 100)
    expected = billed_amount - fee - gst_on_fee - flat_surcharge - refund_amount + fx_adjustment
    return {
        "expected_settlement": round(expected, 2),
        "actual_settlement": settled_amount,
        "residual_gap": round(settled_amount - expected, 2)
    }
```
This runs server-side. The LLM selects the parameters; the function computes the result.

---

## Database Schema (Key Tables)

- `batches`: one per upload; tracks pipeline status, match rates, error counts
- `settlement_records`: rows from the settlement CSV; UNIQUE(batch_id, gateway_txn_id)
- `order_ledger`: rows from the order ledger CSV
- `reconciliation_results`: one per settlement_record; settlement_record_id is NOT NULL; UNIQUE(batch_id, settlement_record_id)
- `exception_candidates`: join table for ambiguous_multiple routing; holds multiple candidate order_ledger_ids
- `reasoning_cards`: one per exception; confidence_score always server-computed
- `audit_log`: immutable event log; event_type is ENUM; indexed on (batch_id, timestamp)

---

## API Endpoints

| Endpoint | Notes |
|---|---|
| POST /batches/upload | Multipart: settlement_file, ledger_file |
| POST /batches/{id}/run-matching | Synchronous |
| POST /batches/{id}/run-reasoning | Async — returns job_id, frontend polls /summary |
| GET /batches/{id}/summary | Poll for batch status; returns full match rate breakdown |
| GET /batches/{id}/exceptions | Paginated; returns reasoning cards |
| POST /reconciliation/{id}/approve | Atomic WHERE status='pending'; 409 on double-action |
| POST /reconciliation/{id}/reject | Same pattern as approve |
| GET /batches/{id}/audit-log | Filterable by event_type, date range |
| GET /batches/{id}/accuracy-report | Joins cards against ground_truth.csv |

---

## File Layout (Expected)

```
/
├── backend/
│   ├── main.py              # FastAPI app + routes
│   ├── models.py            # SQLAlchemy models
│   ├── ingestion.py         # CSV parsing + DB insert
│   ├── matching.py          # Deterministic matching engine
│   ├── reasoning.py         # LLM reasoner + validate_card + compute_confidence
│   ├── approval.py          # Approve/reject endpoints
│   ├── audit.py             # Audit log writes
│   └── schemas.py           # Pydantic request/response schemas
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── UploadPanel.tsx
│   │   │   ├── MatchRateSummaryCard.tsx
│   │   │   ├── ExceptionList.tsx
│   │   │   ├── ReasoningCard.tsx
│   │   │   └── AuditLogViewer.tsx
│   │   └── App.tsx
├── data/
│   ├── synthetic_batch.csv
│   ├── ledger.csv
│   └── ground_truth.csv     # Hidden from reasoner during development
├── docs/                    # All design documents
└── AGENTS.md                # This file
```

---

## Common Mistakes to Avoid

1. Do NOT add `LangGraph` to the core reasoning loop — use LangChain `.batch()` only
2. Do NOT use `fee_deducted` as a gate for the order_id path — it's a sanity flag only
3. Do NOT trust LLM-reported confidence — always run `validate_card()` server-side
4. Do NOT share a single amount confirmation check across the order_id and fallback paths
5. Do NOT allow journal posting without a `human_approved` status in `reconciliation_results`
6. Do NOT use VARCHAR for `event_type` in audit_log — it is an ENUM
7. Do NOT skip the `UNIQUE(batch_id, settlement_record_id)` constraint — idempotency depends on it
