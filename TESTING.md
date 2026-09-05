# Testing Strategy
## Multi-Source Settlement Reconciler

---

## Testing Philosophy

This system handles financial data. Every layer that touches matching logic, confidence scoring, or ledger posting needs a test. The goal is not 100% coverage for its own sake — it's catching the specific failure modes that have already been identified in the design review.

---

## Test Pyramid

```
         ┌──────────────┐
         │  E2E Tests   │  ← 2–3 full pipeline runs against synthetic dataset
         ├──────────────┤
         │ Integration  │  ← API endpoints + DB state assertions
         ├──────────────┤
         │  Unit Tests  │  ← compute_confidence, validate_card, matching algorithm
         └──────────────┘
```

---

## Unit Tests (Run Fast, Run Always)

### `compute_confidence()`
Test the band boundaries explicitly — these are the exact values that map to UI color coding.

```python
def test_compute_confidence_exact_zero():
    score, status = compute_confidence(0.0)
    assert score == 0.99
    assert status == "resolved"

def test_compute_confidence_upper_resolved_band():
    score, status = compute_confidence(0.50)
    assert score == 0.70
    assert status == "resolved"

def test_compute_confidence_just_inside_low_confidence():
    score, status = compute_confidence(0.51)
    assert status == "low_confidence"

def test_compute_confidence_unresolved():
    score, status = compute_confidence(5.01)
    assert score == 0.0
    assert status == "unresolved"

def test_compute_confidence_negative_gap_treated_as_absolute():
    # Negative residual_gap (over-settled) must be handled
    score1, status1 = compute_confidence(0.30)
    score2, status2 = compute_confidence(-0.30)
    assert score1 == score2
    assert status1 == status2
```

### `validate_card()`
```python
def test_validate_card_overrides_llm_category_when_gap_too_large():
    card = {
        "calculation_breakdown": {"residual_gap": 3.40},
        "confidence_score": 0.91,  # LLM claimed high confidence
        "suggested_category": "MDR_VARIANCE",
        "requires_human_review": False
    }
    result = validate_card(card)
    assert result["suggested_category"] == "UNRESOLVED"
    assert result["requires_human_review"] == True
    assert result["confidence_score"] < 0.70  # must match compute_confidence(3.40)

def test_validate_card_preserves_unresolved():
    card = {
        "calculation_breakdown": {"residual_gap": 212.40},
        "confidence_score": 0.0,
        "suggested_category": "UNRESOLVED",
        "requires_human_review": True
    }
    result = validate_card(card)
    assert result["suggested_category"] == "UNRESOLVED"

def test_validate_card_does_not_override_when_gap_is_zero():
    card = {
        "calculation_breakdown": {"residual_gap": 0.00},
        "confidence_score": 0.5,  # LLM reported wrong but gap is 0
        "suggested_category": "MDR_VARIANCE",
        "requires_human_review": True
    }
    result = validate_card(card)
    assert result["confidence_score"] == 0.99
    assert result["suggested_category"] == "MDR_VARIANCE"  # not overridden
```

### `calculate_difference()`
```python
def test_domestic_mdr_only():
    result = calculate_difference(1000.00, 980.00, fee_pct=2.0)
    assert result["expected_settlement"] == 980.00
    assert result["residual_gap"] == 0.00

def test_international_mdr_plus_gst():
    result = calculate_difference(1000.00, 964.60, fee_pct=3.0, gst_on_fee_pct=18.0)
    assert result["expected_settlement"] == 964.60
    assert result["residual_gap"] == 0.00

def test_combined_cause():
    result = calculate_difference(
        1000.00, 934.60,
        fee_pct=3.0, gst_on_fee_pct=18.0,
        flat_surcharge=10.0, refund_amount=20.0
    )
    assert result["residual_gap"] == 0.00

def test_negative_gap_on_over_settlement():
    result = calculate_difference(1000.00, 1010.00, fee_pct=0.0)
    assert result["residual_gap"] == 10.00  # positive: settled > expected
```

### Matching Engine Unit Tests
```python
def test_order_id_match_without_fee_deducted():
    # Must match unconditionally — fee_deducted absence is not a blocker
    record = make_settlement(order_id="ORD-001", settled=980.00, fee_deducted=None)
    ledger = [make_order(order_id="ORD-001", billed=1000.00)]
    result = run_matching([record], ledger)
    assert result[0].status == "matched_deterministic"
    assert result[0].routing_reason == "order_id_match"

def test_order_id_match_with_fee_sanity_pass():
    record = make_settlement(order_id="ORD-001", settled=980.00, fee_deducted=20.00)
    ledger = [make_order(order_id="ORD-001", billed=1000.00)]
    result = run_matching([record], ledger)
    assert result[0].status == "matched_deterministic"

def test_order_id_match_with_fee_sanity_fail_routes_to_exception():
    # order_id matches but fee-adjusted amount is wrong → amount_mismatch
    record = make_settlement(order_id="ORD-001", settled=850.00, fee_deducted=20.00)
    ledger = [make_order(order_id="ORD-001", billed=1000.00)]
    result = run_matching([record], ledger)
    assert result[0].status == "exception_unresolved"
    assert result[0].routing_reason == "amount_mismatch"
    assert result[0].order_ledger_id is not None  # candidate preserved

def test_null_order_id_falls_to_fallback():
    record = make_settlement(order_id=None, settled=980.00, fee_deducted=20.00)
    ledger = [make_order(order_id="ORD-001", billed=1000.00)]
    result = run_matching([record], ledger)
    assert result[0].status == "matched_deterministic"
    assert result[0].routing_reason == "amount_match"

def test_fallback_skipped_when_no_fee_deducted():
    record = make_settlement(order_id=None, settled=980.00, fee_deducted=None)
    ledger = [make_order(order_id="ORD-001", billed=1000.00)]
    result = run_matching([record], ledger)
    assert result[0].routing_reason == "no_match"

def test_currency_mismatch_routes_to_exception():
    record = make_settlement(order_id="ORD-001", currency="USD")
    ledger = [make_order(order_id="ORD-001", currency="INR")]
    result = run_matching([record], ledger)
    assert result[0].routing_reason == "currency_mismatch"

def test_ambiguous_multiple_preserves_all_candidates():
    record = make_settlement(order_id="ORD-DUP", settled=980.00)
    ledger = [
        make_order(order_id="ORD-DUP", billed=1000.00),
        make_order(order_id="ORD-DUP", billed=1000.00)
    ]
    result = run_matching([record], ledger)
    assert result[0].routing_reason == "ambiguous_multiple"
    # Check exception_candidates table has 2 rows

def test_idempotent_rerun():
    # Running matching twice should not create duplicate reconciliation_results rows
    run_matching_on_batch(batch_id)
    run_matching_on_batch(batch_id)
    count = db.query("SELECT COUNT(*) FROM reconciliation_results WHERE batch_id=?", batch_id)
    assert count == EXPECTED_RECORD_COUNT
```

---

## Integration Tests

### Ingestion
```python
def test_upload_creates_batch_and_records():
    response = client.post("/batches/upload", files={"settlement_file": ..., "ledger_file": ...})
    assert response.status_code == 200
    batch_id = response.json()["batch_id"]
    assert db_count("settlement_records", batch_id) == EXPECTED_SETTLEMENT_COUNT
    assert db_count("order_ledger", batch_id) == EXPECTED_LEDGER_COUNT

def test_duplicate_gateway_txn_id_rejected():
    # CSV with repeated gateway_txn_id row — second row must be skipped, not inserted twice
    ...

def test_malformed_rows_counted_in_summary():
    response = client.get(f"/batches/{batch_id}/summary")
    assert response.json()["ingestion_error_count"] > 0
```

### Approve/Reject Concurrency Guard
```python
def test_double_approve_returns_409():
    client.post(f"/reconciliation/{result_id}/approve")
    response2 = client.post(f"/reconciliation/{result_id}/approve")
    assert response2.status_code == 409

def test_approve_then_reject_returns_409():
    client.post(f"/reconciliation/{result_id}/approve")
    response2 = client.post(f"/reconciliation/{result_id}/reject")
    assert response2.status_code == 409

def test_approve_does_not_double_post_journal():
    # Concurrently fire two approvals — check journal entries count == 1
    ...
```

---

## End-to-End: Accuracy Report Test

This is the demo's main proof-of-correctness claim.

```python
def test_full_pipeline_accuracy():
    # 1. Upload synthetic_batch.csv + ledger.csv
    # 2. Run matching — assert ~40 records matched_deterministic
    # 3. Run reasoning — assert ~7 records matched_ai_resolved, ~3 UNRESOLVED
    # 4. Approve all AI-resolved cards
    # 5. GET /batches/{id}/accuracy-report
    # 6. Assert: all 7 explainable records correctly categorized
    # 7. Assert: all 3 unresolvable records correctly flagged UNRESOLVED
    ...
```

---

## Test Data

- `tests/fixtures/clean_settlement.csv` — 10 clean records, all with order_ids
- `tests/fixtures/clean_ledger.csv` — matching 10 ledger entries
- `tests/fixtures/exceptions_settlement.csv` — 5 records with various discrepancies
- `tests/fixtures/exceptions_ledger.csv` — matching ledger entries
- `tests/fixtures/ground_truth.csv` — expected category per exception record

---

## What Not to Test

- LLM output content (non-deterministic) — test that `validate_card()` overrides it correctly instead
- UI visual layout — test data flow and state transitions only
- PostgreSQL internals — trust the DB engine; test your queries

---

## Running Tests

```bash
# Unit tests only (fast, no DB needed)
pytest tests/unit/ -v

# Integration tests (requires DB)
pytest tests/integration/ -v

# Full suite
pytest tests/ -v

# Single test file
pytest tests/unit/test_matching.py -v
```
