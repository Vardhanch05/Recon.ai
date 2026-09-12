# Backend Schema Document
## Multi-Source Settlement Reconciler — PostgreSQL & SQLite Cross-Dialect

---

## Schema Overview

The database layer supports both **PostgreSQL (production ACID)** and **SQLite (local development/testing)** via a platform-independent SQLAlchemy `GUID` type decorator.

All financial state mutations adhere to ACID standards with relational foreign keys, cascade constraints, composite unique indexes for idempotency, and ORM-level immutability enforcement on the audit log.

---

## Enums & Types

### 1. `BatchStatus`
```sql
CREATE TYPE batch_status AS ENUM (
    'uploaded',
    'matching_in_progress',
    'matching_complete',
    'reasoning_in_progress',
    'reasoning_complete',
    'approved',
    'failed'
);
```

### 2. `ReconciliationStatus`
```sql
CREATE TYPE reconciliation_status AS ENUM (
    'matched_deterministic',
    'matched_ai_resolved',
    'exception_unresolved',
    'human_approved',
    'human_rejected'
);
```

### 3. `RoutingReason`
```sql
CREATE TYPE routing_reason AS ENUM (
    'order_id_match',
    'amount_match',
    'amount_mismatch',
    'no_match',
    'ambiguous_multiple',
    'currency_mismatch'
);
```

### 4. `ResolutionSource`
```sql
CREATE TYPE resolution_source AS ENUM (
    'rule_engine',
    'llm_reasoner',
    'human_override'
);
```

### 5. `DiscrepancyCategory`
```sql
CREATE TYPE discrepancy_category_enum AS ENUM (
    'MDR_VARIANCE',
    'PARTIAL_REFUND',
    'FX_ROUNDING',
    'DOMESTIC_MDR',
    'INTERNATIONAL_MDR',
    'GST_ON_FEE',
    'FLAT_SURCHARGE',
    'COMBINED_DISCREPANCY',
    'UNRESOLVED'
);
```

### 6. `AuditEventType`
```sql
CREATE TYPE audit_event_type AS ENUM (
    'ingestion_error',
    'match',
    'llm_call',
    'human_approval',
    'human_rejection',
    'journal_posted'
);
```

---

## Tables & DDL Specification

```sql
-- ─────────────────────────────────────────────
-- BATCHES
-- ─────────────────────────────────────────────
CREATE TABLE batches (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    uploaded_at                 TIMESTAMP NOT NULL DEFAULT NOW(),
    status                      batch_status NOT NULL DEFAULT 'uploaded',
    total_records               INT DEFAULT 0,
    ingestion_error_count       INT NOT NULL DEFAULT 0,
    matched_deterministic_count INT NOT NULL DEFAULT 0,
    matched_ai_resolved_count   INT NOT NULL DEFAULT 0,
    match_rate_deterministic    NUMERIC(5,2),   -- percentage (e.g. 80.00)
    match_rate_ai_resolved      NUMERIC(5,2),   -- percentage (e.g. 12.73)
    unresolved_count            INT DEFAULT 0,
    timestamp_tolerance_seconds INT NOT NULL DEFAULT 2,
    duration_ms                 INT NOT NULL DEFAULT 0
);

-- ─────────────────────────────────────────────
-- SETTLEMENT RECORDS (from Gateway CSV)
-- ─────────────────────────────────────────────
CREATE TABLE settlement_records (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id                UUID NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
    gateway_txn_id          VARCHAR NOT NULL,
    order_id                VARCHAR,           -- nullable: missing or unparseable
    settled_amount          NUMERIC(18,4) NOT NULL,
    settlement_timestamp    TIMESTAMP NOT NULL,
    fee_deducted            NUMERIC(18,4),     -- nullable: gateway reported fee
    currency                VARCHAR(3) NOT NULL DEFAULT 'INR',
    raw_row_json            TEXT,

    CONSTRAINT uq_batch_gateway_txn UNIQUE (batch_id, gateway_txn_id)
);

CREATE INDEX idx_settlement_order_id ON settlement_records (order_id);
CREATE INDEX idx_settlement_batch ON settlement_records (batch_id);

-- ─────────────────────────────────────────────
-- ORDER LEDGER (from Merchant ERP / Internal DB)
-- ─────────────────────────────────────────────
CREATE TABLE order_ledger (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id         UUID NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
    order_id         VARCHAR NOT NULL,
    billed_amount    NUMERIC(18,4) NOT NULL,
    order_timestamp  TIMESTAMP NOT NULL,
    refund_amount    NUMERIC(18,4) DEFAULT 0.0,
    is_international BOOLEAN NOT NULL DEFAULT FALSE,
    payment_method   VARCHAR DEFAULT 'card', -- 'card', 'upi', 'netbanking'
    raw_row_json     TEXT
);

CREATE INDEX idx_ledger_order_id ON order_ledger (order_id);
CREATE INDEX idx_ledger_batch ON order_ledger (batch_id);

-- ─────────────────────────────────────────────
-- RECONCILIATION RESULTS
-- ─────────────────────────────────────────────
CREATE TABLE reconciliation_results (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id                UUID NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
    settlement_record_id    UUID NOT NULL REFERENCES settlement_records(id) ON DELETE CASCADE,
    order_ledger_id         UUID REFERENCES order_ledger(id) ON DELETE SET NULL,
    status                  reconciliation_status NOT NULL,
    routing_reason          routing_reason,
    discrepancy_amount      NUMERIC(18,4),     -- 0 for clean matches, calculated for exceptions
    resolution_source       resolution_source NOT NULL DEFAULT 'rule_engine',
    confidence_score        NUMERIC(5,4),      -- server-computed for AI-resolved rows [0.0000 - 1.0000]
    reviewed_at             TIMESTAMP,         -- populated on human approve/reject
    reviewed_by             VARCHAR,           -- user ID of reviewer
    created_at              TIMESTAMP NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_batch_settlement_reconciliation UNIQUE (batch_id, settlement_record_id)
);

CREATE INDEX idx_results_batch ON reconciliation_results (batch_id);
CREATE INDEX idx_results_status ON reconciliation_results (batch_id, status);

-- ─────────────────────────────────────────────
-- EXCEPTION CANDIDATES (Ambiguous Matches Join)
-- ─────────────────────────────────────────────
CREATE TABLE exception_candidates (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    reconciliation_result_id UUID NOT NULL REFERENCES reconciliation_results(id) ON DELETE CASCADE,
    order_ledger_id          UUID NOT NULL REFERENCES order_ledger(id) ON DELETE CASCADE
);

-- ─────────────────────────────────────────────
-- REASONING CARDS (LLM Exception Cards)
-- ─────────────────────────────────────────────
CREATE TABLE reasoning_cards (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    reconciliation_result_id    UUID NOT NULL REFERENCES reconciliation_results(id) ON DELETE CASCADE UNIQUE,
    hypothesis_text             TEXT NOT NULL,
    calculation_breakdown       TEXT NOT NULL,  -- JSON serialized string
    confidence_score            NUMERIC(5,4) NOT NULL, -- derived from compute_confidence(residual_gap)
    suggested_category          discrepancy_category_enum NOT NULL,
    requires_human_review       BOOLEAN NOT NULL DEFAULT TRUE,
    human_override_note         TEXT,
    created_at                  TIMESTAMP NOT NULL DEFAULT NOW()
);

-- ─────────────────────────────────────────────
-- AUDIT LOG (Append-Only Immutable Event Trail)
-- ─────────────────────────────────────────────
CREATE TABLE audit_log (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id     UUID REFERENCES batches(id) ON DELETE SET NULL,
    event_type   audit_event_type NOT NULL,
    actor        VARCHAR NOT NULL DEFAULT 'system',
    payload_json TEXT,                          -- JSON serialized string
    timestamp    TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_batch_time ON audit_log (batch_id, timestamp);
```

---

## Immutability & Audit Safety Rules

1. **AuditLog Immutability**:
   - SQLAlchemy ORM event listeners (`before_update` and `before_delete`) intercept any modification or deletion attempt and raise an `ImmutableRecordError`.
   - When a `Batch` is deleted, `audit_log.batch_id` is set to `NULL` via `ON DELETE SET NULL`, preserving the historical audit trail permanently.

2. **Strict Idempotency Constraints**:
   - `uq_batch_gateway_txn` ensures duplicate settlement transactions cannot be injected within the same batch.
   - `uq_batch_settlement_reconciliation` ensures that re-running deterministic matching or AI reasoning updates records in-place rather than generating duplicate reconciliation entries.

3. **Calculation Breakdown Schema**:
```json
{
  "billed_amount": 1000.0,
  "fee_pct_tested": 3.0,
  "gst_on_fee_pct_tested": 18.0,
  "flat_surcharge_tested": 0.0,
  "refund_amount_tested": 0.0,
  "fx_adjustment_tested": 0.0,
  "expected_settlement": 964.6,
  "actual_settlement": 964.6,
  "residual_gap": 0.0,
  "attempts_tried": ["domestic_mdr", "intl_mdr"]
}
```
