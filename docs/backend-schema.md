# Backend Schema Document
## Multi-Source Settlement Reconciler — PostgreSQL

---

## Schema: Full DDL

```sql
-- ─────────────────────────────────────────────
-- ENUMS
-- ─────────────────────────────────────────────

CREATE TYPE batch_status AS ENUM (
    'uploaded',
    'matching_complete',
    'reasoning_complete',
    'failed'
);

CREATE TYPE reconciliation_status AS ENUM (
    'matched_deterministic',
    'matched_ai_resolved',
    'exception_unresolved',
    'human_approved',
    'human_rejected'
);

CREATE TYPE routing_reason AS ENUM (
    'order_id_match',
    'amount_match',
    'amount_mismatch',
    'no_match',
    'ambiguous_multiple',
    'currency_mismatch'
);

CREATE TYPE resolution_source AS ENUM (
    'rule_engine',
    'llm_reasoner',
    'human_override'
);

CREATE TYPE audit_event_type AS ENUM (
    'ingestion_error',
    'match',
    'llm_call',
    'human_approval',
    'human_rejection',
    'journal_posted'
);

-- ─────────────────────────────────────────────
-- TABLES
-- ─────────────────────────────────────────────

CREATE TABLE batches (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    uploaded_at                 TIMESTAMP NOT NULL DEFAULT NOW(),
    status                      batch_status NOT NULL DEFAULT 'uploaded',
    total_records               INT,
    ingestion_error_count       INT NOT NULL DEFAULT 0,
    match_rate_deterministic    DECIMAL(5,2),   -- null until matching_complete
    match_rate_ai_resolved      DECIMAL(5,2),   -- null until reasoning_complete
    unresolved_count            INT,
    timestamp_tolerance_seconds INT NOT NULL DEFAULT 2
);

CREATE TABLE settlement_records (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id                UUID NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
    gateway_txn_id          VARCHAR NOT NULL,
    order_id                VARCHAR,           -- nullable: may be missing/unparseable
    settled_amount          DECIMAL(12,2) NOT NULL,
    settlement_timestamp    TIMESTAMP NOT NULL,
    -- ASSUMPTION: settlement_timestamp is the original transaction timestamp
    -- echoed back by the gateway, NOT the T+2 credit-posting time.
    fee_deducted            DECIMAL(12,2),     -- nullable: not all files include this
    currency                VARCHAR(3) NOT NULL DEFAULT 'INR',
    raw_row_json            JSONB NOT NULL,

    CONSTRAINT uq_settlement_txn UNIQUE (batch_id, gateway_txn_id)
);

CREATE TABLE order_ledger (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id         UUID NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
    order_id         VARCHAR NOT NULL,
    billed_amount    DECIMAL(12,2) NOT NULL,
    order_timestamp  TIMESTAMP NOT NULL,
    refund_amount    DECIMAL(12,2),            -- nullable
    is_international BOOLEAN NOT NULL DEFAULT FALSE,
    payment_method   VARCHAR,                  -- 'card', 'upi', 'netbanking'
    raw_row_json     JSONB NOT NULL
);

CREATE TABLE reconciliation_results (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id                UUID NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
    settlement_record_id    UUID NOT NULL REFERENCES settlement_records(id),
    order_ledger_id         UUID REFERENCES order_ledger(id),  -- nullable when no match
    status                  reconciliation_status NOT NULL DEFAULT 'exception_unresolved',
    routing_reason          routing_reason,
    discrepancy_amount      DECIMAL(12,2),     -- 0 for clean matches, null until computed
    resolution_source       resolution_source,
    confidence_score        DECIMAL(3,2),      -- only for AI-resolved rows
    reviewed_at             TIMESTAMP,         -- populated on human approve/reject
    reviewed_by             VARCHAR,           -- user ID of reviewer
    created_at              TIMESTAMP NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_result_per_settlement UNIQUE (batch_id, settlement_record_id)
    -- No CHECK (settlement_record_id IS NOT NULL) needed — column is NOT NULL above
);

-- For ambiguous_multiple routing: store all candidate order_ledger_ids
CREATE TABLE exception_candidates (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    reconciliation_result_id UUID NOT NULL REFERENCES reconciliation_results(id) ON DELETE CASCADE,
    order_ledger_id         UUID NOT NULL REFERENCES order_ledger(id),
    CONSTRAINT uq_candidate UNIQUE (reconciliation_result_id, order_ledger_id)
);

CREATE TABLE reasoning_cards (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    reconciliation_result_id    UUID NOT NULL REFERENCES reconciliation_results(id) ON DELETE CASCADE,
    hypothesis_text             TEXT NOT NULL,
    calculation_breakdown       JSONB NOT NULL,
    -- Shape: { billed_amount, fee_pct_tested, gst_on_fee_pct_tested,
    --          flat_surcharge_tested, refund_amount_tested, fx_adjustment_tested,
    --          expected_settlement, actual_settlement, residual_gap,
    --          attempts_tried[] (for UNRESOLVED) }
    confidence_score            DECIMAL(3,2) NOT NULL,  -- server-computed, never LLM self-reported
    suggested_category          VARCHAR NOT NULL,       -- MDR_VARIANCE | PARTIAL_REFUND | FX_ROUNDING | UNRESOLVED
    requires_human_review       BOOLEAN NOT NULL DEFAULT TRUE,
    human_override_note         TEXT                    -- nullable: accountant's rejection reason
);

CREATE TABLE audit_log (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id     UUID NOT NULL,
    event_type   audit_event_type NOT NULL,
    actor        VARCHAR NOT NULL,   -- 'system', 'llm', or user_id
    payload_json JSONB NOT NULL,     -- full context, never updated after insert
    timestamp    TIMESTAMP NOT NULL DEFAULT NOW()
);

-- ─────────────────────────────────────────────
-- INDEXES
-- ─────────────────────────────────────────────

CREATE INDEX idx_audit_batch_time ON audit_log (batch_id, timestamp);
CREATE INDEX idx_settlement_batch ON settlement_records (batch_id);
CREATE INDEX idx_ledger_batch ON order_ledger (batch_id);
CREATE INDEX idx_results_batch ON reconciliation_results (batch_id);
CREATE INDEX idx_results_status ON reconciliation_results (batch_id, status);
CREATE INDEX idx_cards_result ON reasoning_cards (reconciliation_result_id);
```

---

## Key Design Decisions

| Decision | Rationale |
|---|---|
| `settlement_record_id` NOT NULL on `reconciliation_results` | Every reconciliation originates from a settlement record — no orphaned rows |
| `UNIQUE(batch_id, settlement_record_id)` | Idempotency guarantee — re-running matching never creates duplicates |
| `UNIQUE(batch_id, gateway_txn_id)` | Prevents duplicate rows from a repeated CSV |
| `event_type` as ENUM | Prevents string inconsistency bugs in audit log filtering |
| `exception_candidates` join table | `order_ledger_id` is a single FK — can't hold multiple ambiguous candidates in one column |
| `confidence_score` on `reasoning_cards` computed server-side | LLM self-reported confidence is unreliable and indefensible |
| `calculation_breakdown` as JSONB | Schema-flexible for varying hypothesis types; rendered as a table in UI |

---

## `calculation_breakdown` JSONB Shape

For resolved cases:
```json
{
  "billed_amount": 1000.00,
  "fee_pct_tested": 3.0,
  "gst_on_fee_pct_tested": 18.0,
  "flat_surcharge_tested": 10.0,
  "refund_amount_tested": 0.00,
  "fx_adjustment_tested": 0.00,
  "expected_settlement": 954.60,
  "actual_settlement": 954.60,
  "residual_gap": 0.00
}
```

For unresolved cases:
```json
{
  "residual_gap": 212.40,
  "attempts_tried": ["domestic_mdr", "intl_mdr", "partial_refund", "combined_mdr_refund"]
}
```
