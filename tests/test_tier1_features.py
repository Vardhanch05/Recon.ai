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
