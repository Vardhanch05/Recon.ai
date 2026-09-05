# API Reference

## Multi-Source Settlement Reconciler — FastAPI Backend

Base URL: `http://localhost:8000`

---

## POST /batches/upload

Upload settlement and ledger CSV files. Creates a new batch.

**Request** — multipart/form-data:

```
settlement_file: <CSV file>
ledger_file:     <CSV file>
timestamp_tolerance_seconds: 2  (optional, default 2)
```

**Response 200:**

```json
{
  "batch_id": "uuid",
  "total_records": 55,
  "ingestion_error_count": 0,
  "status": "uploaded"
}
```

**Response 409** — duplicate batch (same file detected):

```json
{ "detail": "Batch already exists. Set confirm_overwrite=true to replace." }
```

**Notes:**

- Malformed rows are skipped and counted, not rejected
- Each valid row is inserted into `settlement_records` or `order_ledger`
- UNIQUE(batch_id, gateway_txn_id) enforced at DB level — duplicate rows within CSV are skipped

---

## POST /batches/{batch_id}/run-matching

Trigger deterministic matching pass. Synchronous — returns when complete.

**Response 200:**

```json
{
  "batch_id": "uuid",
  "status": "matching_complete",
  "matched_deterministic_count": 44,
  "exception_count": 11,
  "match_rate_deterministic_pct": 80.0
}
```

**Response 404** — batch not found

**Notes:**

- Idempotent — re-running does not create duplicate `reconciliation_results` rows (UNIQUE constraint)
- Each exception is tagged with `routing_reason`: `amount_mismatch`, `no_match`, `ambiguous_multiple`, `currency_mismatch`
- `ambiguous_multiple` candidates stored in `exception_candidates` table

---

## POST /batches/{batch_id}/run-reasoning

Trigger LLM reasoning pass on all exceptions. Asynchronous — returns job_id immediately.

**Response 202:**

```json
{
  "batch_id": "uuid",
  "job_id": "uuid",
  "exception_count": 11,
  "message": "Reasoning started. Poll /summary for completion status."
}
```

**Notes:**

- Backend runs exceptions in parallel via LangChain `.batch()`
- Poll `GET /batches/{id}/summary` until `status == "reasoning_complete"`
- Each exception gets one reasoning card
- `validate_card()` runs server-side before any card is written to DB

---

## GET /batches/{batch_id}/summary

Returns current batch status and match rate breakdown. Frontend polls this endpoint.

**Response 200:**

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

**Status values:**

- `uploaded` — ingestion complete, matching not yet run
- `matching_complete` — deterministic pass done, reasoning not yet run
- `reasoning_complete` — full pipeline complete
- `failed` — pipeline error (check audit log)

**Notes:**

- `match_rate_ai_resolved_pct` is null until `reasoning_complete`
- Frontend should show "--" for null values, not 0

---

## GET /batches/{batch_id}/exceptions

Returns all reasoning cards for human review. Paginated.

**Query params:**

- `?limit=20` (default 20)
- `?offset=0` (default 0)
- `?status=exception_unresolved` (optional filter)

**Response 200:**

```json
{
  "total": 11,
  "items": [
    {
      "reconciliation_result_id": "uuid",
      "settlement_record": {
        "gateway_txn_id": "TXN-001",
        "settled_amount": 964.6,
        "currency": "INR"
      },
      "discrepancy_amount": 35.4,
      "routing_reason": "amount_mismatch",
      "reasoning_card": {
        "id": "uuid",
        "hypothesis_text": "Shortfall matches 18% GST on 3% international MDR fee.",
        "calculation_breakdown": {
          "billed_amount": 1000.0,
          "fee_pct_tested": 3.0,
          "gst_on_fee_pct_tested": 18.0,
          "flat_surcharge_tested": 0.0,
          "refund_amount_tested": 0.0,
          "fx_adjustment_tested": 0.0,
          "expected_settlement": 964.6,
          "actual_settlement": 964.6,
          "residual_gap": 0.0
        },
        "confidence_score": 0.99,
        "suggested_category": "MDR_VARIANCE",
        "requires_human_review": false
      },
      "status": "exception_unresolved"
    }
  ]
}
```

---

## POST /reconciliation/{result_id}/approve

Human approves a reasoning card. Triggers journal posting.

**Request body** (optional):

```json
{ "reviewed_by": "user_id_123" }
```

**Response 200:**

```json
{
  "result_id": "uuid",
  "status": "human_approved",
  "journal_posted": true,
  "reviewed_at": "2024-01-15T14:31:15Z"
}
```

**Response 409** — already actioned:

```json
{ "detail": "This record has already been actioned." }
```

**Notes:**

- Atomic: `UPDATE reconciliation_results SET status='human_approved' WHERE id=:id AND status='exception_unresolved'`
- If rowcount == 0 → 409
- Journal entry written in same transaction as status update
- Logs `human_approval` + `journal_posted` to audit_log

---

## POST /reconciliation/{result_id}/reject

Human rejects a reasoning card. Flags for manual handling.

**Request body** (optional):

```json
{
  "reviewed_by": "user_id_123",
  "override_note": "This looks like a bank error, not an MDR issue."
}
```

**Response 200:**

```json
{
  "result_id": "uuid",
  "status": "human_rejected",
  "reviewed_at": "2024-01-15T14:32:00Z"
}
```

**Response 409** — already actioned:

```json
{ "detail": "This record has already been actioned." }
```

**Notes:**

- Same atomic pattern as approve: `WHERE status='exception_unresolved'`
- No journal entry posted
- `override_note` stored in `reasoning_cards.human_override_note`
- Logs `human_rejection` to audit_log

---

## GET /batches/{batch_id}/audit-log

Returns immutable event log for the batch.

**Query params:**

- `?event_type=llm_call` (optional filter)
- `?from=2024-01-15T14:00:00` (optional)
- `?to=2024-01-15T15:00:00` (optional)
- `?limit=50&offset=0`

**Response 200:**

```json
{
  "total": 87,
  "items": [
    {
      "id": "uuid",
      "event_type": "match",
      "actor": "system",
      "timestamp": "2024-01-15T14:30:01Z",
      "payload_json": {
        "settlement_record_id": "uuid",
        "order_ledger_id": "uuid",
        "routing_reason": "order_id_match",
        "discrepancy_amount": 0.0
      }
    }
  ]
}
```

---

## GET /batches/{batch_id}/accuracy-report

Compares reasoning cards against ground-truth answer key. Used for demo accuracy claim.

**Query params:**

- `?ground_truth_path=data/ground_truth.csv` (path relative to server)

**Response 200:**

```json
{
  "batch_id": "uuid",
  "total_non_trivial_records": 10,
  "explainable_records": {
    "total": 7,
    "correct": 7,
    "accuracy_pct": 100.0,
    "breakdown": [
      {
        "gateway_txn_id": "TXN-011",
        "true_category": "MDR_VARIANCE",
        "predicted": "MDR_VARIANCE",
        "correct": true
      }
    ]
  },
  "unresolvable_records": {
    "total": 3,
    "correctly_flagged_unresolved": 3,
    "accuracy_pct": 100.0
  },
  "overall_accuracy_pct": 100.0
}
```

---

## Error Responses

| Status | Meaning                                                 |
| ------ | ------------------------------------------------------- |
| 400    | Bad request (malformed input, missing required field)   |
| 404    | Batch or result not found                               |
| 409    | Conflict — duplicate batch or already-actioned approval |
| 422    | Validation error (Pydantic)                             |
| 500    | Internal server error — check audit_log for details     |
