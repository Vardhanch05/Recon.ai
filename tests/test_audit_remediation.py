import pytest
import uuid
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.main import app
from backend.models import (
    Batch, BatchStatus, AuditLog, AuditEventType, SettlementRecord,
    OrderLedger, ReconciliationResult, ReconciliationStatus,
    RoutingReason, ImmutableRecordError, DiscrepancyCategory
)
from backend.ingestion import clean_currency
from backend.reasoning import process_single_exception, evaluate_hypotheses_deterministically
from tests.conftest import TestingSessionLocal

client = TestClient(app)


def test_clean_currency_robustness():
    """Verifies that clean_currency handles negative values, various symbols, and edge cases."""
    assert clean_currency("₹1,200.50") == 1200.50
    assert clean_currency("$49.00") == 49.00
    assert clean_currency("€99.95") == 99.95
    assert clean_currency("£150.00") == 150.00
    assert clean_currency("-₹500.00") == -500.00
    assert clean_currency("($250.00)") == -250.00
    assert clean_currency(" - 100.50 ") == -100.50
    assert clean_currency(None) == 0.0
    assert clean_currency("") == 0.0
    assert clean_currency(123.45) == 123.45


def test_audit_log_immutability_orm_guard(db_session: Session):
    """Verifies that updating or deleting AuditLog records raises ImmutableRecordError."""
    log_entry = AuditLog(
        id=uuid.uuid4(),
        event_type=AuditEventType.match,
        actor="system",
        payload_json='{"test": 1}',
        timestamp=datetime.now(timezone.utc).replace(tzinfo=None)
    )
    db_session.add(log_entry)
    db_session.commit()

    # Attempt UPDATE
    log_entry.actor = "malicious_actor"
    with pytest.raises(ImmutableRecordError):
        db_session.commit()
    db_session.rollback()

    # Attempt DELETE
    entry_to_delete = db_session.query(AuditLog).filter(AuditLog.id == log_entry.id).first()
    db_session.delete(entry_to_delete)
    with pytest.raises(ImmutableRecordError):
        db_session.commit()
    db_session.rollback()


def test_audit_log_persists_on_batch_delete(db_session: Session):
    """Verifies that deleting a Batch does not cascade-delete its audit log records."""
    batch = Batch(
        id=uuid.uuid4(),
        status=BatchStatus.uploaded,
        total_records=1
    )
    db_session.add(batch)
    db_session.commit()

    log_entry = AuditLog(
        id=uuid.uuid4(),
        batch_id=batch.id,
        event_type=AuditEventType.match,
        actor="rule_engine",
        payload_json='{"status": "ok"}',
        timestamp=datetime.now(timezone.utc).replace(tzinfo=None)
    )
    db_session.add(log_entry)
    db_session.commit()

    # Delete the batch
    db_session.delete(batch)
    db_session.commit()

    # Audit log should still exist in database
    remaining_log = db_session.query(AuditLog).filter(AuditLog.id == log_entry.id).first()
    assert remaining_log is not None
    assert remaining_log.event_type == AuditEventType.match


def test_missing_ledger_match_reasoning(db_session: Session):
    """Verifies that exceptions with no ledger match are classified as UNRESOLVED with 0 confidence."""
    import asyncio
    settlement_data = {
        "gateway_txn_id": "pay_test_no_ledger",
        "settled_amount": 1950.00,
        "settlement_timestamp": datetime.now(timezone.utc).isoformat()
    }
    
    # Process exception with None candidate_order
    card, actor = asyncio.run(process_single_exception(
        result_id=uuid.uuid4(),
        settlement_data=settlement_data,
        candidate_order=None,
        db=db_session
    ))
    
    assert card["suggested_category"] == DiscrepancyCategory.UNRESOLVED.value
    assert card["confidence_score"] == 0.0
    assert card["requires_human_review"] is True


def test_atomic_concurrency_guard_on_reasoning(db_session: Session):
    """Verifies that trigger_reasoning rejects duplicate concurrent runs with 409 Conflict."""
    batch = Batch(
        id=uuid.uuid4(),
        status=BatchStatus.matching_complete,
        total_records=10
    )
    db_session.add(batch)
    db_session.commit()

    # First trigger should succeed
    res1 = client.post(f"/batches/{batch.id}/run-reasoning")
    assert res1.status_code == 202

    # Second trigger should be rejected with 409 Conflict because status is reasoning_in_progress
    res2 = client.post(f"/batches/{batch.id}/run-reasoning")
    assert res2.status_code == 409
    assert "already in progress" in res2.json()["detail"]


def test_upload_rejects_non_csv():
    """Verifies that non-csv files are rejected on upload."""
    res = client.post(
        "/batches/upload",
        files={
            "settlement_file": ("settlement.txt", b"order_id,amount", "text/plain"),
            "ledger_file": ("ledger.csv", b"order_id,billed_amount", "text/csv"),
        }
    )
    assert res.status_code == 400
    assert "Only CSV files" in res.json()["detail"]
