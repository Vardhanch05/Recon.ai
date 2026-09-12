# Testing Strategy & Automated Test Suite
## Multi-Source Settlement Reconciler

---

## 1. Testing Philosophy

In financial systems, correctness and deterministic execution are non-negotiable. Our automated test suite guarantees:
1. **Mathematical Accuracy**: Zero reliance on LLM self-reported arithmetic.
2. **Concurrency Safety**: Strict atomic database locks preventing duplicate journal entries or race conditions.
3. **Data Integrity & Immutability**: ORM-level protection preventing modification or deletion of the audit trail.
4. **Resilient Parsing**: Handling dirty currencies, non-standard timestamps, and malformed rows gracefully.

---

## 2. Test Architecture & Pytest Suite Breakdown

The repository contains 12 comprehensive automated test suites across 6 specialized test modules in `tests/`:

```
tests/
├── conftest.py                   # Pytest fixtures, test database setup, and mock CSV helpers
├── test_health.py                # Health check and root ping endpoints
├── test_models.py                # SQLAlchemy cross-dialect GUID, relationships, and unique constraints
├── test_ingestion.py             # CSV parsing, currency cleaning, error logging, and summary endpoints
├── test_matching.py              # Deterministic matching engine, fallback matching, and approval guards
├── test_full_pipeline.py         # End-to-end reconciliation pipeline from upload to AI reasoning & approval
└── test_audit_remediation.py     # ORM immutability hooks, audit persistence on batch delete, & concurrency
```

---

## 3. Test Modules & Covered Scenarios

### 3.1 `test_health.py`
- `test_health_check`: Verifies the `/health` endpoint connects to the active database engine and returns HTTP 200.
- `test_root`: Verifies the root greeting endpoint.

### 3.2 `test_models.py`
- `test_models_and_constraints`: Verifies cascade deletes, platform-independent `GUID` type handling, and composite unique constraints (`uq_batch_gateway_txn` and `uq_batch_settlement_reconciliation`).

### 3.3 `test_ingestion.py`
- `test_upload_and_summary`: Tests multipart file upload for both Razorpay settlement and order ledger CSVs, verifies row counts, and tests the `/batches/{id}/summary` endpoint.

### 3.4 `test_matching.py`
- `test_deterministic_matching_and_approval_guards`: Tests exact order ID matching, fee sanity checks, amount+timestamp fallback logic, atomic double-action 409 protections on `/approve` and `/reject`, and audit event emission.

### 3.5 `test_full_pipeline.py`
- `test_full_reconciliation_pipeline`: Executes the full end-to-end flow:
  1. Uploads 55-record synthetic batch.
  2. Runs deterministic matching (verifying 80% auto-match rate).
  3. Triggers parallel AI discrepancy reasoning.
  4. Fetches and validates paginated reasoning cards.
  5. Performs human approval and rejection workflows.
  6. Evaluates confusion matrix accuracy against `data/ground_truth.csv`.

### 3.6 `test_audit_remediation.py`
- `test_clean_currency_robustness`: Validates that dirty currency strings with symbols (`₹`, `$`, `€`), commas (`1,000.50`), and spaces are parsed cleanly into floats.
- `test_audit_log_immutability_orm_guard`: Verifies that ORM event listeners intercept and reject any attempt to update or delete `AuditLog` rows.
- `test_audit_log_persists_on_batch_delete`: Verifies that deleting a `Batch` sets `audit_log.batch_id` to `NULL` via `ON DELETE SET NULL`, preserving the audit history permanently.
- `test_missing_ledger_match_reasoning`: Verifies that settlements with no corresponding ledger candidate are safely routed to `UNRESOLVED` reasoning cards.
- `test_atomic_concurrency_guard_on_reasoning`: Verifies atomic SQL state transitions on `/batches/{id}/run-reasoning` to prevent duplicate concurrent executions.
- `test_upload_rejects_non_csv`: Verifies non-CSV file rejection with HTTP 400.

---

## 4. Running the Test Suite

### Run All Tests
```bash
pytest -v
```

### Run With Coverage Report
```bash
pytest --cov=backend tests/
```

### Run Specific Test Module
```bash
pytest tests/test_audit_remediation.py -v
```

---

## 5. Automated Verification Output

```text
============================= test session starts =============================
collected 12 items

tests/test_audit_remediation.py::test_clean_currency_robustness PASSED   [  8%]
tests/test_audit_remediation.py::test_audit_log_immutability_orm_guard PASSED [ 16%]
tests/test_audit_remediation.py::test_audit_log_persists_on_batch_delete PASSED [ 25%]
tests/test_audit_remediation.py::test_missing_ledger_match_reasoning PASSED [ 33%]
tests/test_audit_remediation.py::test_atomic_concurrency_guard_on_reasoning PASSED [ 41%]
tests/test_audit_remediation.py::test_upload_rejects_non_csv PASSED      [ 50%]
tests/test_full_pipeline.py::test_full_reconciliation_pipeline PASSED    [ 58%]
tests/test_health.py::test_health_check PASSED                           [ 66%]
tests/test_health.py::test_root PASSED                                   [ 75%]
tests/test_ingestion.py::test_upload_and_summary PASSED                  [ 83%]
tests/test_matching.py::test_deterministic_matching_and_approval_guards PASSED [ 91%]
tests/test_models.py::test_models_and_constraints PASSED                 [100%]

======================== 12 passed in 5.18s ========================
```
