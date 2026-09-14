# Audit Log Reference
## Multi-Source Settlement Reconciler

---

## Purpose

The audit log is an immutable, append-only record of every significant event in the reconciliation pipeline. It is the source of truth for:
- Demonstrating to judges that every AI decision was human-reviewed
- Debugging any discrepancy between expected and actual match rates
- Proving the sequence of events for any given settlement record

---

## Schema

```sql
CREATE TABLE audit_log (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id     UUID NOT NULL,
    event_type   audit_event_type NOT NULL,  -- ENUM, not VARCHAR
    actor        VARCHAR NOT NULL,           -- 'system', 'llm', or user_id
    payload_json JSONB NOT NULL,             -- full context, never updated
    timestamp    TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_batch_time ON audit_log (batch_id, timestamp);
```

---

## Event Types

| event_type | actor | When Written | payload_json contains |
|---|---|---|---|
| `ingestion_error` | `system` | On malformed CSV row during upload | `{ row_number, raw_content, error_message }` |
| `match` | `system` | On each deterministic match | `{ settlement_record_id, order_ledger_id, routing_reason, discrepancy_amount }` |
| `llm_call` | `llm` | After each LLM reasoning call completes | `{ exception_id, hypothesis_text, residual_gap, confidence_score, suggested_category, model_used, latency_ms }` |
| `human_approval` | `<user_id>` | When accountant clicks Approve | `{ reconciliation_result_id, reasoning_card_id, reviewed_by }` |
| `human_rejection` | `<user_id>` | When accountant clicks Reject | `{ reconciliation_result_id, reasoning_card_id, reviewed_by, override_note }` |
| `journal_posted` | `system` | After journal entry written on approval | `{ reconciliation_result_id, amount, currency }` |

---

## Immutability Rules

- Rows are INSERT-only. No UPDATE or DELETE is permitted on `audit_log`.
- `payload_json` captures full context at the time of the event — not foreign key references that could change later.
- The sequence of events for any `batch_id` is verifiable by ordering on `timestamp`.

---

## Query Examples

### All events for a batch in order
```sql
SELECT event_type, actor, timestamp, payload_json
FROM audit_log
WHERE batch_id = :batch_id
ORDER BY timestamp ASC;
```

### All LLM calls for a batch
```sql
SELECT payload_json->>'hypothesis_text', payload_json->>'confidence_score'
FROM audit_log
WHERE batch_id = :batch_id AND event_type = 'llm_call'
ORDER BY timestamp;
```

### All human decisions
```sql
SELECT event_type, actor, timestamp,
       payload_json->>'reconciliation_result_id' AS result_id
FROM audit_log
WHERE batch_id = :batch_id
AND event_type IN ('human_approval', 'human_rejection')
ORDER BY timestamp;
```

### Ingestion errors
```sql
SELECT payload_json->>'row_number', payload_json->>'error_message'
FROM audit_log
WHERE batch_id = :batch_id AND event_type = 'ingestion_error';
```

---

## API Access

`GET /batches/{batch_id}/audit-log`

Query params:
- `?event_type=llm_call` — filter by event type
- `?from=2024-01-15T14:00:00` — filter from timestamp
- `?to=2024-01-15T15:00:00` — filter to timestamp

Response: paginated list of audit events, ordered by timestamp ascending.

---

## Demo Usage

When demonstrating to judges, the audit log proves:
1. Every LLM call is logged with its exact hypothesis and confidence score
2. Every human approval/rejection is logged with the reviewer's identity
3. Journal entries are only posted after human approval
4. No records were silently skipped or force-matched

Show the audit log filter by `event_type=human_approval` to demonstrate the human-in-the-loop requirement is enforced in the data, not just the UI.
