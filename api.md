# Recon.ai API Reference

Base URL: `http://localhost:8000`  
OpenAPI Documentation: `http://localhost:8000/docs`

---

## Authentication & Headers

| Header | Description | Required |
|---|---|---|
| `X-API-Key` | API key token for protected endpoints | Optional in development; required in production if `REQUIRE_API_KEY=true` |
| `Content-Type` | `multipart/form-data` (upload) or `application/json` | Required |

---

## Endpoints

### 1. Ingest Batch
`POST /batches/upload`

Uploads Razorpay settlement CSV and merchant order ledger CSV, creates a new batch, and persists records.

**Request** — `multipart/form-data`:
- `settlement_file`: CSV file (required)
- `ledger_file`: CSV file (required)
- `timestamp_tolerance_seconds`: integer (optional, default: `2`)
- `confirm_overwrite`: boolean (optional, default: `false`)

**Response 200 OK**:
```json
{
  "batch_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "total_records": 55,
  "ingestion_error_count": 0,
  "status": "uploaded"
}
```

**Errors**:
- `400 Bad Request`: Non-CSV file uploaded or empty file.
- `413 Request Entity Too Large`: File exceeds 50MB limit or 50,000 row ceiling.
- `409 Conflict`: Duplicate batch detected when `confirm_overwrite=false`.

---

### 2. Run Deterministic Matching
`POST /batches/{batch_id}/run-matching`

Executes two-pass deterministic matching engine (exact order ID match and timestamp/amount fallback).

**Response 200 OK**:
```json
{
  "batch_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "status": "matching_complete",
  "matched_deterministic_count": 44,
  "exception_count": 11,
  "match_rate_deterministic_pct": 80.0
}
```

**Errors**:
- `404 Not Found`: Batch ID does not exist.
- `409 Conflict`: Batch is not in `uploaded` status.

---

### 3. Run AI Discrepancy Reasoning
`POST /batches/{batch_id}/run-reasoning`

Triggers asynchronous LLM reasoning pass on all exception records using the `calculate_difference()` arithmetic verification tool.

**Response 202 Accepted**:
```json
{
  "batch_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "job_id": "8f8b3400-349c-4613-8d26-0e95bc7291a2",
  "exception_count": 11,
  "message": "Reasoning started. Poll /summary for completion status."
}
```

**Errors**:
- `404 Not Found`: Batch ID does not exist.
- `409 Conflict`: Reasoning is already in progress or already completed for this batch.
- `400 Bad Request`: Batch is not in `matching_complete` status.

---

### 4. Get Batch Summary
`GET /batches/{batch_id}/summary`

Returns real-time batch pipeline progress, match rate breakdown, and execution throughput.

**Response 200 OK**:
```json
{
  "batch_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "status": "reasoning_complete",
  "total_records": 55,
  "matched_deterministic_count": 44,
  "matched_ai_resolved_count": 7,
  "unresolved_count": 3,
  "ingestion_error_count": 0,
  "match_rate_deterministic_pct": 80.0,
  "match_rate_ai_resolved_pct": 12.73,
  "throughput_ms": 4200
}
```

---

### 5. List Exceptions & Reasoning Cards
`GET /batches/{batch_id}/exceptions`

Returns paginated exception records, candidate orders, and LLM reasoning cards.

**Query Parameters**:
- `limit`: integer (default: `20`, max: `100`)
- `offset`: integer (default: `0`)
- `status`: string (optional filter: `exception_unresolved`, `matched_ai_resolved`, `human_approved`, `human_rejected`)

**Response 200 OK**:
```json
{
  "total": 11,
  "items": [
    {
      "reconciliation_result_id": "8a72b0c1-2f3b-4c5e-9a1d-7b2c3d4e5f6a",
      "settlement_record": {
        "gateway_txn_id": "TXN_SYNTH_045",
        "order_id": "ORD_SYNTH_045",
        "settled_amount": 964.6,
        "settlement_timestamp": "2024-03-01T10:00:00",
        "fee_deducted": 35.4,
        "currency": "INR"
      },
      "candidate_orders": [
        {
          "order_id": "ORD_SYNTH_045",
          "billed_amount": 1000.0,
          "order_timestamp": "2024-03-01T09:59:58",
          "refund_amount": 0.0,
          "is_international": true,
          "payment_method": "card"
        }
      ],
      "discrepancy_amount": 35.4,
      "routing_reason": "amount_mismatch",
      "status": "matched_ai_resolved",
      "reasoning_card": {
        "id": "1c2d3e4f-5a6b-7c8d-9e0f-1a2b3c4d5e6f",
        "hypothesis_text": "Settlement difference is fully explained by 3.0% International Card MDR fee (₹30.00) plus 18.0% GST on fee (₹5.40).",
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
        "suggested_category": "INTERNATIONAL_MDR",
        "requires_human_review": false,
        "human_override_note": null
      }
    }
  ]
}
```

---

### 6. Human Approve Reasoning Card
`POST /reconciliation/{result_id}/approve`

Human accountant approves an AI-resolved discrepancy, marks status as `human_approved`, and triggers journal posting.

**Request Body** (optional):
```json
{
  "reviewed_by": "controller_sarah"
}
```

**Response 200 OK**:
```json
{
  "result_id": "8a72b0c1-2f3b-4c5e-9a1d-7b2c3d4e5f6a",
  "status": "human_approved",
  "journal_posted": true,
  "reviewed_at": "2024-03-01T10:05:00"
}
```

**Errors**:
- `400 Bad Request`: Attempting to approve an `UNRESOLVED` record.
- `409 Conflict`: Record has already been approved or rejected (atomic concurrency lock).

---

### 7. Human Reject Reasoning Card
`POST /reconciliation/{result_id}/reject`

Human accountant rejects an AI hypothesis or routes an unresolved exception to manual escalation.

**Request Body** (optional):
```json
{
  "reviewed_by": "controller_sarah",
  "override_note": "Gateway discrepancy exceeds standard fee tier; escalating to bank support."
}
```

**Response 200 OK**:
```json
{
  "result_id": "8a72b0c1-2f3b-4c5e-9a1d-7b2c3d4e5f6a",
  "status": "human_rejected",
  "reviewed_at": "2024-03-01T10:05:30"
}
```

---

### 8. Get Immutable Audit Log
`GET /batches/{batch_id}/audit-log`

Retrieves append-only audit trail records for a batch.

**Query Parameters**:
- `event_type`: string (optional filter: `ingestion_error`, `match`, `llm_call`, `human_approval`, `human_rejection`, `journal_posted`)

**Response 200 OK**:
```json
{
  "total": 48,
  "events": [
    {
      "id": "e4f5a6b7-c8d9-0e1f-2a3b-4c5d6e7f8a9b",
      "batch_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
      "event_type": "match",
      "actor": "system",
      "payload_json": {
        "settlement_record_id": "b1c2d3e4-f5a6-7b8c-9d0e-1f2a3b4c5d6e",
        "order_ledger_id": "c2d3e4f5-a6b7-8c9d-0e1f-2a3b4c5d6e7f",
        "routing_reason": "order_id_match",
        "discrepancy_amount": 0.0
      },
      "timestamp": "2024-03-01T10:01:05"
    }
  ]
}
```

---

### 9. Get Accuracy Report
`GET /batches/{batch_id}/accuracy-report`

Evaluates AI reasoning card predictions against ground-truth answer key.

**Query Parameters**:
- `ground_truth_path`: string (default: `"data/ground_truth.csv"`)

**Response 200 OK**:
```json
{
  "total_evaluated": 10,
  "explainable_total": 7,
  "explainable_correct": 7,
  "explainable_accuracy_pct": 100.0,
  "unresolvable_total": 3,
  "unresolvable_correct": 3,
  "unresolvable_accuracy_pct": 100.0,
  "overall_accuracy_pct": 100.0,
  "confusion_matrix": {
    "true_positives_explainable": 7,
    "true_negatives_unresolvable": 3,
    "false_positives": 0,
    "false_negatives": 0,
    "category_breakdown": {
      "DOMESTIC_MDR": { "total": 2, "correct": 2 },
      "INTERNATIONAL_MDR": { "total": 2, "correct": 2 },
      "PARTIAL_REFUND": { "total": 1, "correct": 1 },
      "FLAT_SURCHARGE": { "total": 1, "correct": 1 },
      "COMBINED_DISCREPANCY": { "total": 1, "correct": 1 },
      "UNRESOLVED": { "total": 3, "correct": 3 }
    }
  }
}
```

---

---

### 10. Maker-Checker Propose Resolution
`POST /reconciliation/{result_id}/propose`

Maker step: An accountant proposes resolution on an AI-resolved discrepancy, transitioning status to `pending_authorization`.

**Request Body** (optional):
```json
{
  "proposed_by": "alice_maker",
  "note": "MDR rate verified against merchant agreement tier 2."
}
```

**Response 200 OK**:
```json
{
  "result_id": "8a72b0c1-2f3b-4c5e-9a1d-7b2c3d4e5f6a",
  "status": "pending_authorization",
  "proposed_by": "alice_maker",
  "proposed_at": "2024-03-01T10:05:00",
  "requires_maker_checker": true,
  "message": "Proposal recorded. Awaiting secondary controller authorization."
}
```

**Errors**:
- `404 Not Found`: Record not found.
- `409 Conflict`: Record is already proposed or actioned.
- `400 Bad Request`: Only AI-resolved records can be proposed.

---

### 11. Maker-Checker Authorize Resolution
`POST /reconciliation/{result_id}/authorize`

Checker step: Secondary controller authorizes a proposed resolution and triggers journal posting. Enforces segregation of duties (`403 Forbidden` if Maker == Checker).

**Request Body** (optional):
```json
{
  "authorized_by": "bob_controller"
}
```

**Response 200 OK**:
```json
{
  "result_id": "8a72b0c1-2f3b-4c5e-9a1d-7b2c3d4e5f6a",
  "status": "human_approved",
  "proposed_by": "alice_maker",
  "authorized_by": "bob_controller",
  "journal_posted": true,
  "authorized_at": "2024-03-01T10:10:00"
}
```

**Errors**:
- `403 Forbidden`: Self-authorization attempt (Maker attempted to authorize their own proposal).
- `409 Conflict`: Record is not in `pending_authorization` status or already authorized/rejected.

---

### 12. Verify Cryptographic Audit Chain
`GET /batches/audit-log/verify` or `GET /batches/{batch_id}/audit-log/verify`

Cryptographically validates SHA-256 hash continuity and verifies all payload hashes from sequence 1 to N to detect any in-place record tampering.

**Response 200 OK**:
```json
{
  "is_valid": true,
  "total_verified_events": 150,
  "batch_events_count": 55,
  "latest_sequence": 150,
  "head_hash": "a1b2c3d4e5f6...",
  "message": "Audit chain is cryptographically intact and unbroken."
}
```

---

### 13. Health Check
`GET /health`

Verifies server status and database connectivity.

**Response 200 OK**:
```json
{
  "status": "ok",
  "app": "Multi-Source Settlement Reconciler (Recon.ai)",
  "database": "connected"
}
```
