# Technical Requirements Document (TRD)
## Multi-Source Settlement Reconciler

---

## 1. Tech Stack

| Layer | Technology | Rationale |
|---|---|---|
| Backend | FastAPI (Python) | Async support, easy background tasks, strong typing with Pydantic |
| Database | PostgreSQL | ACID guarantees required for financial ledger data |
| Frontend | React | Component-based UI matches the reasoning card pattern |
| LLM | OpenAI GPT-4o or Anthropic Claude (function-calling capable) | Tool-calling required for `calculate_difference` |
| LLM Orchestration | LangChain `.batch()` for parallel exception processing | No LangGraph — single call per record, no stateful loop needed |
| Background Tasks | FastAPI `BackgroundTasks` (or Celery if needed) | Async LLM reasoning pass |
| ORM | SQLAlchemy or raw psycopg2 | Preference for raw SQL on financial queries |

---

## 2. Functional Requirements

### FR-1: Ingestion
- Accept multipart form POST with two CSV files: `settlement_file`, `ledger_file`
- Parse using Python `csv` module or pandas
- Validate each row: required fields present, amounts are valid decimals, timestamps parseable
- On malformed row: log to `audit_log` as `ingestion_error`, skip row, increment `batches.ingestion_error_count`
- Insert into `settlement_records` and `order_ledger` tables
- Enforce `UNIQUE(batch_id, gateway_txn_id)` — reject duplicate transaction rows at DB level
- On duplicate batch upload: return 409 with prompt to confirm overwrite

### FR-2: Deterministic Matching
- Primary path: query `order_ledger` WHERE `order_id = settlement_record.order_id` (null-safe)
- On order_id match found (exactly one): accept as `matched_deterministic`
  - If `fee_deducted` is present, run sanity check: `abs(billed - fee_deducted - settled) < 0.01`
  - If sanity fails: route as `amount_mismatch`, preserve `order_ledger_id`
  - If no `fee_deducted` or sanity passes: mark `matched_deterministic`
- Fallback path (no order_id candidates): filter by `abs((billed - fee_deducted) - settled) < 0.01 AND abs(order_ts - settlement_ts) <= tolerance_seconds`
  - Only runs if `fee_deducted IS NOT NULL`
- Write `reconciliation_results` row with `routing_reason`
- Enforce idempotency via `UNIQUE(batch_id, settlement_record_id)` — upsert pattern on re-run

### FR-3: Exception Routing
- Records not matched deterministically enter exception queue with `routing_reason` tag
- `ambiguous_multiple`: all candidate `order_ledger_id`s stored (UUID[] column or join table)
- Exception queue is a DB query, not an in-memory queue — survives process restarts

### FR-4: LLM Reasoning
- Build context object per exception (see LLD §5.1)
- Call LLM with `calculate_difference` as a registered function/tool
- `calculate_difference` signature: `(billed_amount, settled_amount, fee_pct=0, gst_on_fee_pct=0, flat_surcharge=0, refund_amount=0, fx_adjustment=0)`
- LLM must call tool — if it returns free-text math instead, reject the response and retry once
- After LLM response: run `validate_card()` server-side before writing to DB
- `validate_card()` calls `compute_confidence(residual_gap)` and overrides LLM's confidence/category
- On LLM timeout/failure: retry once; on second failure write `UNRESOLVED` with note "LLM unavailable"
- Run exceptions in parallel via LangChain `.batch()` — not sequentially

### FR-5: Reasoning Cards
- Write one `reasoning_cards` row per exception
- `confidence_score` always computed server-side from `residual_gap`, never LLM self-reported
- `suggested_category` overridden to `UNRESOLVED` if `computed_status != "resolved"`

### FR-6: Human Approval
- `POST /reconciliation/{result_id}/approve`: atomic `UPDATE WHERE status='pending'`; 409 if rowcount=0
- `POST /reconciliation/{result_id}/reject`: same pattern; records `reviewed_by`, `reviewed_at`
- On approve: write journal entry, log `journal_posted` to audit_log
- On reject: set `human_rejected`, store optional `human_override_note`

### FR-7: Audit Log
- Write to `audit_log` on: ingestion_error, match, llm_call, human_approval, human_rejection, journal_posted
- `payload_json` stores full context — never updated after write
- Index on `(batch_id, timestamp)` for query performance

---

## 3. Non-Functional Requirements

| Requirement | Target |
|---|---|
| Deterministic matching latency | <1 second for 50 records |
| LLM reasoning latency (parallel) | <15 seconds for 10 exception records |
| Approval endpoint response time | <200ms (DB-only operation) |
| Concurrent approval safety | 409 on double-action, zero duplicate journal entries |
| Data integrity | All financial writes use DB transactions |
| Idempotency | Re-running any pipeline stage produces identical results |

---

## 4. Security Requirements (hackathon scope)

- No PII logging beyond what's in `raw_row_json` (synthetic data — acceptable for demo)
- LLM API key stored as environment variable, never in code or logs
- No authentication required for hackathon demo (note as production gap)

---

## 5. Confidence Score Formula

```python
def compute_confidence(residual_gap: float) -> tuple[float, str]:
    gap = abs(residual_gap)
    if gap <= 0.05:
        confidence = 0.99 - (gap / 0.05) * 0.04   # 0.99 → 0.95
        status = "resolved"
    elif gap <= 0.50:
        confidence = 0.94 - ((gap - 0.05) / 0.45) * 0.24  # 0.94 → 0.70
        status = "resolved"
    elif gap <= 5.00:  # threshold to be calibrated against synthetic data
        confidence = 0.69 - ((gap - 0.50) / 4.50) * 0.39  # 0.69 → 0.30
        status = "low_confidence"
    else:
        confidence = 0.0
        status = "unresolved"
    return round(confidence, 2), status
```

This function is the single source of truth for confidence and status. `validate_card()` derives both values from it — no separate threshold constants.

---

## 6. Environment Variables Required

```
DATABASE_URL=postgresql://user:pass@localhost:5432/reconciler
LLM_API_KEY=...
LLM_MODEL=gpt-4o          # or claude-3-5-sonnet
LLM_TIMEOUT_SECONDS=30
TIMESTAMP_TOLERANCE_DEFAULT=2
```
