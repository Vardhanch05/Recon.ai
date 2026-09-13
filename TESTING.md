# Testing Strategy & Automated Test Suite
## Multi-Source Settlement Reconciler

---

## 1. Testing Philosophy

In financial systems, correctness and deterministic execution are non-negotiable. Our automated test suite guarantees:
1. **Mathematical Precision**: Quantized `Decimal("0.01")` calculations eliminate floating-point drift, with isolated server-side arithmetic tools.
2. **Concurrency Safety & Atomic Guards**: Strict single-state atomic database locks preventing duplicate matching or reasoning race conditions.
3. **Dual-Control Governance**: Segregation of duties enforcing `HTTP 403 Forbidden` on Maker self-authorization attempts before leaking state.
4. **Data Integrity & Cryptographic Audit Trail**: Forward-linked SHA-256 hash chaining with ORM-level immutability hooks blocking modification or deletion.
5. **Crash-Resilient Reasoning**: 5-minute lease timeout auto-reclamation and chunked commits (`CHUNK_SIZE = 10`) balancing throughput with rollback granularity.

---

## 2. Test Architecture & Pytest Suite Breakdown

The repository contains 21 comprehensive automated test suites across 7 specialized test modules in `tests/`:

```
tests/
├── conftest.py                   # Pytest fixtures, test database setup, and mock CSV helpers
├── test_health.py                # Health check and root ping endpoints
├── test_models.py                # SQLAlchemy cross-dialect GUID, relationships, and unique constraints
├── test_ingestion.py             # CSV parsing, currency cleaning, error logging, and summary endpoints
├── test_matching.py              # Deterministic matching engine, fallback joins, and math sanity checks
├── test_full_pipeline.py         # End-to-end reconciliation pipeline from upload to AI reasoning & approval
├── test_audit_remediation.py     # ORM immutability hooks, audit persistence on batch delete, & concurrency
└── test_tier1_features.py        # Cryptographic hash chains, Maker-Checker guards, lease reclamation, & Decimal tests
```

---

## 3. Test Modules & Covered Scenarios

### 3.1 `test_tier1_features.py` (9 Tests)
- `test_cryptographic_hash_chain_verification_and_tamper_detection`: Verifies forward SHA-256 hash linking across pipeline events and validates tamper detection upon payload mutation.
- `test_maker_checker_dual_control_and_403_self_authorization_guard`: Verifies Segregation of Duties, confirming identity check returns HTTP 403 on self-authorization before status evaluation.
- `test_multi_hypothesis_sequential_state_graph_telemetry`: Verifies multi-hypothesis reasoning state graph transitions and parameter telemetry.
- `test_run_matching_concurrency_and_status_guard`: Verifies atomic single-state guard on `/batches/{id}/run-matching` returning HTTP 409 on duplicate/re-run attempts.
- `test_reasoning_lease_timeout_and_force_retry_reclamation`: Verifies 5-minute lease timeout auto-reclamation and `force_retry=true` parameter.
- `test_direct_ingestion_functions_produce_chained_audit_logs`: Verifies that direct ingestion function calls route through chained audit logging.
- `test_decimal_financial_precision_and_json_roundtrip`: Verifies `Decimal("0.01")` quantization against real IEEE-754 floating point subtraction failure modes (`58.95 - 57.771 != 1.179`).
- `test_matching_sanity_gap_centralized_math`: Verifies centralized math calculation (`calculate_difference`) in matching sanity checks.
- `test_confirm_overwrite_duplicate_prevention_and_throughput_telemetry`: Verifies idempotency duplicate handling on `/batches/upload` and real duration telemetry in `throughput_ms`.

### 3.2 `test_audit_remediation.py` (6 Tests)
- `test_clean_currency_robustness`: Validates that dirty currency strings with symbols (`₹`, `$`, `€`), commas (`1,000.50`), and spaces are parsed cleanly.
- `test_audit_log_immutability_orm_guard`: Verifies that ORM event listeners intercept and reject any attempt to update or delete `AuditLog` rows.
- `test_audit_log_persists_on_batch_delete`: Verifies that deleting a `Batch` preserves audit history permanently.
- `test_missing_ledger_match_reasoning`: Verifies that settlements with no corresponding ledger candidate route to `UNRESOLVED` reasoning cards.
- `test_atomic_concurrency_guard_on_reasoning`: Verifies atomic SQL state transitions on `/batches/{id}/run-reasoning`.
- `test_upload_rejects_non_csv`: Verifies non-CSV file rejection with HTTP 400.

### 3.3 `test_matching.py` (1 Test)
- `test_deterministic_matching_and_approval_guards`: Tests exact order ID matching, fee sanity checks, amount+timestamp fallback logic, and atomic double-action 409 protections.

### 3.4 `test_full_pipeline.py` (1 Test)
- `test_full_reconciliation_pipeline`: Executes the complete multi-source pipeline from upload to AI reasoning, approval, and accuracy reporting.

### 3.5 `test_ingestion.py` (1 Test)
- `test_upload_and_summary`: Tests multipart file upload for settlement and ledger CSVs, verifies row counts, and tests the `/batches/{id}/summary` endpoint.

### 3.6 `test_models.py` (1 Test)
- `test_models_and_constraints`: Verifies cascade deletes, platform-independent `GUID` type handling, and composite unique constraints.

### 3.7 `test_health.py` (2 Tests)
- `test_health_check`: Verifies the `/health` database connection.
- `test_root`: Verifies the root greeting endpoint.

---

## 4. Running the Test Suite

### Run All Tests
```bash
pytest -v
```

### Run Specific Test Module
```bash
pytest tests/test_tier1_features.py -v
```

---

## 5. Automated Verification Output

```text
============================= test session starts =============================
platform win32 -- Python 3.14.3, pytest-9.1.1, pluggy-1.6.0
collected 21 items

tests/test_audit_remediation.py::test_clean_currency_robustness PASSED   [  4%]
tests/test_audit_remediation.py::test_audit_log_immutability_orm_guard PASSED [  9%]
tests/test_audit_remediation.py::test_audit_log_persists_on_batch_delete PASSED [ 14%]
tests/test_audit_remediation.py::test_missing_ledger_match_reasoning PASSED [ 19%]
tests/test_audit_remediation.py::test_atomic_concurrency_guard_on_reasoning PASSED [ 23%]
tests/test_audit_remediation.py::test_upload_rejects_non_csv PASSED      [ 28%]
tests/test_full_pipeline.py::test_full_reconciliation_pipeline PASSED    [ 33%]
tests/test_health.py::test_health_check PASSED                           [ 38%]
tests/test_health.py::test_root PASSED                                   [ 42%]
tests/test_ingestion.py::test_upload_and_summary PASSED                  [ 47%]
tests/test_matching.py::test_deterministic_matching_and_approval_guards PASSED [ 52%]
tests/test_models.py::test_models_and_constraints PASSED                 [ 57%]
tests/test_tier1_features.py::test_cryptographic_hash_chain_verification_and_tamper_detection PASSED [ 61%]
tests/test_tier1_features.py::test_maker_checker_dual_control_and_403_self_authorization_guard PASSED [ 66%]
tests/test_tier1_features.py::test_multi_hypothesis_sequential_state_graph_telemetry PASSED [ 71%]
tests/test_tier1_features.py::test_run_matching_concurrency_and_status_guard PASSED [ 76%]
tests/test_tier1_features.py::test_reasoning_lease_timeout_and_force_retry_reclamation PASSED [ 80%]
tests/test_tier1_features.py::test_direct_ingestion_functions_produce_chained_audit_logs PASSED [ 85%]
tests/test_tier1_features.py::test_decimal_financial_precision_and_json_roundtrip PASSED [ 90%]
tests/test_tier1_features.py::test_matching_sanity_gap_centralized_math PASSED [ 95%]
tests/test_tier1_features.py::test_confirm_overwrite_duplicate_prevention_and_throughput_telemetry PASSED [100%]

======================== 21 passed, 1 warning in 4.09s ========================
```
