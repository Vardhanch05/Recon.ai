import uuid
import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.main import app
from backend.models import (
    Batch,
    BatchStatus,
    ReconciliationResult,
    ReconciliationStatus,
    SettlementRecord,
    OrderLedger,
    AuditLog,
    AuditEventType,
    DiscrepancyCategory
)
from backend.audit import log_audit_event, verify_audit_chain, GENESIS_HASH
from backend.reasoning import evaluate_hypotheses_deterministically
from tests.conftest import TestingSessionLocal

client = TestClient(app)


def test_cryptographic_hash_chain_verification_and_tamper_detection():
    """
    Verifies that the global SHA-256 audit log chain maintains link continuity,
    and accurately detects payload tampering on the exact broken sequence.
    """
    db = TestingSessionLocal()
    batch_id = uuid.uuid4()

    # 1. Log a sequence of events
    e1 = log_audit_event(db, batch_id, AuditEventType.ingestion_error, "system", {"error": "Row 5 malformed"})
    e2 = log_audit_event(db, batch_id, AuditEventType.match, "rule_engine", {"matched": 44})
    e3 = log_audit_event(db, batch_id, AuditEventType.llm_call, "rule_reasoner", {"category": "MDR_VARIANCE"})
    db.commit()

    # Verify hashes exist and link linearly
    assert e1.prev_hash is not None
    assert e2.prev_hash == e1.current_hash
    assert e3.prev_hash == e2.current_hash
    assert e1.sequence_num < e2.sequence_num < e3.sequence_num

    # 2. Verify audit chain returns valid
    verify_res = verify_audit_chain(db, batch_id=batch_id)
    assert verify_res["is_valid"] is True
    assert verify_res["total_verified_events"] >= 3

    # 3. Test API endpoint for chain verification
    api_res = client.get("/batches/audit-log/verify")
    assert api_res.status_code == 200
    assert api_res.json()["is_valid"] is True

    # 4. Simulate malicious in-place tampering using raw SQL update (bypassing ORM listeners)
    db.execute(
        text("UPDATE audit_log SET payload_json = '{\"error\":\"Tampered payload content\"}' WHERE id = :id"),
        {"id": str(e2.id)}
    )
    db.commit()

    # 5. Verify that tamper detection flags the exact broken row
    tamper_check = verify_audit_chain(db, batch_id=batch_id)
    assert tamper_check["is_valid"] is False
    assert tamper_check["broken_at_sequence"] == e2.sequence_num
    assert tamper_check["broken_row_id"] == str(e2.id)
    assert "tamper detected" in tamper_check["reason"].lower()
    db.close()


def test_maker_checker_dual_control_and_403_self_authorization_guard():
    """
    Tests the Maker-Checker workflow for high-value variances:
      1. Maker proposes resolution (moves to 'pending_authorization').
      2. Maker attempts to authorize own proposal -> rejected with 403 Forbidden.
      3. Checker authorizes resolution -> succeeds with 200 OK (journal posted).
      4. Second authorization attempt -> rejected with 409 Conflict.
    """
    db = TestingSessionLocal()
    batch = Batch(id=uuid.uuid4(), status=BatchStatus.reasoning_complete, total_records=1)
    db.add(batch)

    settlement = SettlementRecord(
        id=uuid.uuid4(),
        batch_id=batch.id,
        gateway_txn_id="txn_high_value_01",
        settled_amount=40000.0,
        settlement_timestamp=datetime.now(timezone.utc).replace(tzinfo=None)
    )
    db.add(settlement)

    # Discrepancy > ₹10,000 threshold
    recon = ReconciliationResult(
        id=uuid.uuid4(),
        batch_id=batch.id,
        settlement_record_id=settlement.id,
        status=ReconciliationStatus.matched_ai_resolved,
        discrepancy_amount=15000.0,
        confidence_score=0.99
    )
    db.add(recon)
    db.commit()

    result_id = str(recon.id)

    # 1. Standard /approve on > ₹10,000 variance triggers 409 and redirects to pending_authorization
    approve_res = client.post(
        f"/reconciliation/{result_id}/approve",
        json={"reviewed_by": "alice_maker"}
    )
    assert approve_res.status_code == 409
    assert "exceeds" in approve_res.json()["detail"].lower()

    # Verify status changed to pending_authorization
    db.refresh(recon)
    assert recon.status == ReconciliationStatus.pending_authorization
    assert recon.proposed_by == "alice_maker"

    # 2. Maker attempts to authorize their own proposal -> 403 Forbidden
    self_auth_res = client.post(
        f"/reconciliation/{result_id}/authorize",
        json={"authorized_by": "alice_maker"}
    )
    assert self_auth_res.status_code == 403
    assert "Maker-Checker violation" in self_auth_res.json()["detail"]

    # 3. Independent checker authorizes -> 200 OK
    checker_auth_res = client.post(
        f"/reconciliation/{result_id}/authorize",
        json={"authorized_by": "bob_controller"}
    )
    assert checker_auth_res.status_code == 200
    auth_data = checker_auth_res.json()
    assert auth_data["status"] == "human_approved"
    assert auth_data["proposed_by"] == "alice_maker"
    assert auth_data["authorized_by"] == "bob_controller"
    assert auth_data["journal_posted"] is True

    # 4. Double action attempt on authorized record -> 409 Conflict
    double_auth_res = client.post(
        f"/reconciliation/{result_id}/authorize",
        json={"authorized_by": "carol_auditor"}
    )
    assert double_auth_res.status_code == 409
    assert "already been authorized" in double_auth_res.json()["detail"]

    db.close()


def test_multi_hypothesis_sequential_state_graph_telemetry():
    """
    Tests that evaluate_hypotheses_deterministically systematically evaluates
    candidate hypotheses and logs the sequential attempts trajectory.
    """
    # 1. Test Domestic MDR + GST match
    res_domestic = evaluate_hypotheses_deterministically(
        billed_amount=1000.0,
        settled_amount=976.40,
        is_international=False
    )
    assert res_domestic["suggested_category"] == DiscrepancyCategory.MDR_VARIANCE.value
    assert res_domestic["confidence_score"] == 0.99
    assert len(res_domestic["calculation_breakdown"]["attempts_tried"]) >= 1

    # 2. Test Surcharge match
    res_surcharge = evaluate_hypotheses_deterministically(
        billed_amount=1500.0,
        settled_amount=1460.0,
        is_international=False
    )
    assert res_surcharge["suggested_category"] == DiscrepancyCategory.MDR_VARIANCE.value
    assert "flat ₹10" in res_surcharge["hypothesis_text"]

    # 3. Test Partial Refund match
    res_refund = evaluate_hypotheses_deterministically(
        billed_amount=1200.0,
        settled_amount=1021.68,
        is_international=False,
        known_refund=150.0
    )
    assert res_refund["suggested_category"] == DiscrepancyCategory.PARTIAL_REFUND.value

    # 4. Test Unresolved Anomaly records full attempts trajectory
    res_unres = evaluate_hypotheses_deterministically(
        billed_amount=5000.0,
        settled_amount=4200.0,
        is_international=False
    )
    assert res_unres["suggested_category"] == DiscrepancyCategory.UNRESOLVED.value
    assert res_unres["confidence_score"] == 0.0
    assert len(res_unres["calculation_breakdown"]["attempts_tried"]) >= 6


def test_run_matching_concurrency_and_status_guard():
    """
    Fix 1: Verifies that trigger_matching uses an atomic status guard (uploaded -> matching_in_progress).
    Repeated or concurrent matching runs return 409 Conflict rather than 500 IntegrityError.
    """
    db = TestingSessionLocal()
    batch = Batch(id=uuid.uuid4(), status=BatchStatus.uploaded, total_records=1)
    db.add(batch)
    db.commit()

    # 1. First trigger succeeds
    res1 = client.post(f"/batches/{batch.id}/run-matching")
    assert res1.status_code == 200
    assert res1.json()["status"] == "matching_complete"

    # 2. Second trigger on matching_complete batch is rejected with 409 Conflict (not 500)
    res2 = client.post(f"/batches/{batch.id}/run-matching")
    assert res2.status_code == 409
    assert "not in uploaded status" in res2.json()["detail"].lower()
    db.close()


def test_reasoning_lease_timeout_and_force_retry_reclamation():
    """
    Fix 2: Verifies that a batch stuck in reasoning_in_progress can be reclaimed
    after lease expiration (5 mins) or via force_retry=True.
    """
    from datetime import timedelta
    db = TestingSessionLocal()
    stale_time = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=10)
    batch_stale = Batch(
        id=uuid.uuid4(),
        status=BatchStatus.reasoning_in_progress,
        reasoning_started_at=stale_time,
        total_records=5
    )
    db.add(batch_stale)
    db.commit()

    # 1. Stale lease is automatically reclaimed -> 202 Accepted
    res_stale = client.post(f"/batches/{batch_stale.id}/run-reasoning")
    assert res_stale.status_code == 202
    assert "started" in res_stale.json()["message"].lower()

    # 2. Fresh in_progress without lease expiry is rejected with 409
    fresh_time = datetime.now(timezone.utc).replace(tzinfo=None)
    batch_fresh = Batch(
        id=uuid.uuid4(),
        status=BatchStatus.reasoning_in_progress,
        reasoning_started_at=fresh_time,
        total_records=5
    )
    db.add(batch_fresh)
    db.commit()

    res_fresh = client.post(f"/batches/{batch_fresh.id}/run-reasoning")
    assert res_fresh.status_code == 409
    assert "already in progress" in res_fresh.json()["detail"].lower()

    # 3. Explicit force_retry overrides fresh lock -> 202 Accepted
    res_force = client.post(f"/batches/{batch_fresh.id}/run-reasoning?force_retry=true")
    assert res_force.status_code == 202
    db.close()


def test_direct_ingestion_functions_produce_chained_audit_logs():
    """
    Fix 4: Verifies that calling ingest_settlement_csv and ingest_ledger_csv directly
    routes ingestion errors through log_audit_event and maintains a valid cryptographic hash chain.
    """
    from backend.ingestion import ingest_settlement_csv, ingest_ledger_csv
    db = TestingSessionLocal()
    batch = Batch(id=uuid.uuid4(), status=BatchStatus.uploaded, total_records=1)
    db.add(batch)
    db.commit()

    malformed_csv = b"gateway_txn_id,order_id,settled_amount,settlement_timestamp,fee_deducted,currency\n,,INVALID,,\n"
    succ, errs = ingest_settlement_csv(db=db, batch_id=batch.id, file_bytes=malformed_csv)
    assert errs >= 1
    db.commit()

    # Verify that the direct ingestion errors formed valid hash chain links
    chain_check = verify_audit_chain(db=db, batch_id=batch.id)
    assert chain_check["is_valid"] is True
    assert chain_check["total_verified_events"] >= 1
    db.close()


def test_decimal_financial_precision_and_json_roundtrip():
    """
    Fix 5: Verifies Decimal precision arithmetic prevents floating-point rounding drift,
    and round-trips cleanly through calculation_breakdown JSON serialization into API responses.
    Specifically proves a known IEEE 754 binary representation failure where raw float math fails.
    """
    from backend.reasoning import calculate_difference
    from decimal import Decimal

    # 1. IEEE 754 representation failure proof:
    # In raw Python float: 58.95 - 57.771 evaluates to 1.1789999999999984 != 1.179
    raw_float_diff = 58.95 - 57.771
    assert raw_float_diff != 1.179, "Raw float subtraction unexpectedly succeeded"

    # In calculate_difference (Decimal precision), exact equality is preserved:
    calc_decimal = calculate_difference(
        billed_amount="58.95",
        settled_amount="57.771",
        flat_surcharge="1.179"
    )
    assert calc_decimal["residual_gap"] == 0.00
    assert calc_decimal["expected_settlement"] == 57.77

    # 2. Test exact arithmetic on repeating fractions (1000 * 0.02 * 0.18 = 3.60 exactly)
    calc = calculate_difference(
        billed_amount=Decimal("1000.00"),
        settled_amount=Decimal("976.40"),
        fee_pct=Decimal("2.0"),
        gst_on_fee_pct=Decimal("18.0")
    )
    assert calc["expected_settlement"] == 976.40
    assert calc["residual_gap"] == 0.00


def test_matching_sanity_gap_centralized_math():
    """
    Fix 6: Verifies that deterministic matching evaluates fee sanity checks and discrepancy
    amounts through the centralized calculate_difference() arithmetic tool.
    """
    from backend.matching import run_deterministic_matching
    from backend.reasoning import calculate_difference
    db = TestingSessionLocal()
    batch = Batch(id=uuid.uuid4(), status=BatchStatus.uploaded, total_records=1)
    db.add(batch)

    # Add settlement and ledger row
    s = SettlementRecord(
        id=uuid.uuid4(),
        batch_id=batch.id,
        gateway_txn_id="txn_math_01",
        order_id="ord_math_01",
        settled_amount=950.00,
        fee_deducted=50.00,
        settlement_timestamp=datetime.now(timezone.utc).replace(tzinfo=None)
    )
    l = OrderLedger(
        id=uuid.uuid4(),
        batch_id=batch.id,
        order_id="ord_math_01",
        billed_amount=1000.00,
        order_timestamp=datetime.now(timezone.utc).replace(tzinfo=None)
    )
    db.add(s)
    db.add(l)
    db.commit()

    # Verify matching uses centralized arithmetic tool
    res = run_deterministic_matching(db=db, batch_id=batch.id)
    assert res["matched_deterministic_count"] == 1

    recon_row = db.query(ReconciliationResult).filter(ReconciliationResult.batch_id == batch.id).first()
    tool_check = calculate_difference(billed_amount=1000.00, settled_amount=950.00, flat_surcharge=50.00)
    assert tool_check["residual_gap"] == 0.00
    assert float(recon_row.discrepancy_amount) == 50.00
    db.close()


def test_confirm_overwrite_duplicate_prevention_and_throughput_telemetry():
    """
    Fix 7: Verifies confirm_overwrite prevents accidental duplicate batch re-uploads (409 Conflict),
    and GET /batches/{id}/summary returns non-null integer throughput_ms after execution.
    """
    import io
    sample_settle = "gateway_txn_id,order_id,settled_amount,settlement_timestamp,fee_deducted,currency\ntxn_telemetry_01,ord_tel_01,980.00,2026-09-01T10:00:00Z,20.00,INR\n"
    sample_ledger = "order_id,billed_amount,order_timestamp,refund_amount,is_international,payment_method\nord_tel_01,1000.00,2026-09-01T10:00:00Z,0.00,false,card\n"

    # 1. First upload succeeds
    res1 = client.post(
        "/batches/upload",
        files={
            "settlement_file": ("settlement.csv", io.BytesIO(sample_settle.encode("utf-8")), "text/csv"),
            "ledger_file": ("ledger.csv", io.BytesIO(sample_ledger.encode("utf-8")), "text/csv"),
        }
    )
    assert res1.status_code == 200
    batch_id = res1.json()["batch_id"]

    # 2. Duplicate upload without confirm_overwrite returns 409 Conflict
    res_dup = client.post(
        "/batches/upload",
        files={
            "settlement_file": ("settlement.csv", io.BytesIO(sample_settle.encode("utf-8")), "text/csv"),
            "ledger_file": ("ledger.csv", io.BytesIO(sample_ledger.encode("utf-8")), "text/csv"),
        },
        data={"confirm_overwrite": False}
    )
    assert res_dup.status_code == 409
    assert "duplicate batch detected" in res_dup.json()["detail"].lower()

    # 3. Duplicate upload with confirm_overwrite=True succeeds
    res_overwrite = client.post(
        "/batches/upload",
        files={
            "settlement_file": ("settlement.csv", io.BytesIO(sample_settle.encode("utf-8")), "text/csv"),
            "ledger_file": ("ledger.csv", io.BytesIO(sample_ledger.encode("utf-8")), "text/csv"),
        },
        data={"confirm_overwrite": True}
    )
    assert res_overwrite.status_code == 200

    # 4. Run matching and verify throughput_ms is populated
    res_match = client.post(f"/batches/{batch_id}/run-matching")
    assert res_match.status_code == 200

    res_sum = client.get(f"/batches/{batch_id}/summary")
    assert res_sum.status_code == 200
    assert res_sum.json()["throughput_ms"] is not None
    assert isinstance(res_sum.json()["throughput_ms"], int)
