import uuid
from datetime import datetime
import pytest
from sqlalchemy.exc import IntegrityError
from backend.models import (
    Batch,
    BatchStatus,
    SettlementRecord,
    OrderLedger,
    ReconciliationResult,
    ReconciliationStatus,
    RoutingReason,
    ResolutionSource,
    ExceptionCandidate,
    ReasoningCard,
    AuditLog,
    AuditEventType
)

def test_models_and_constraints(db_session):
    # 1. Create a Batch
    batch = Batch(
        status=BatchStatus.uploaded,
        total_records=10,
        timestamp_tolerance_seconds=2
    )
    db_session.add(batch)
    db_session.commit()
    assert batch.id is not None
    assert batch.status == BatchStatus.uploaded

    # 2. Create a SettlementRecord
    settle_rec = SettlementRecord(
        batch_id=batch.id,
        gateway_txn_id="pay_12345",
        order_id="order_999",
        settled_amount=950.00,
        settlement_timestamp=datetime.utcnow(),
        fee_deducted=50.00,
        currency="INR",
        raw_row_json='{"gateway_txn_id": "pay_12345", "amount": 950.00}'
    )
    db_session.add(settle_rec)
    db_session.commit()
    assert settle_rec.id is not None

    # 3. Create an OrderLedger row
    ledger_rec = OrderLedger(
        batch_id=batch.id,
        order_id="order_999",
        billed_amount=1000.00,
        order_timestamp=datetime.utcnow(),
        refund_amount=0.00,
        is_international=False,
        payment_method="card",
        raw_row_json='{"order_id": "order_999", "amount": 1000.00}'
    )
    db_session.add(ledger_rec)
    db_session.commit()
    assert ledger_rec.id is not None

    # 4. Create a ReconciliationResult
    recon_res = ReconciliationResult(
        batch_id=batch.id,
        settlement_record_id=settle_rec.id,
        order_ledger_id=ledger_rec.id,
        status=ReconciliationStatus.matched_ai_resolved,
        routing_reason=RoutingReason.amount_mismatch,
        discrepancy_amount=50.00,
        resolution_source=ResolutionSource.llm_reasoner,
        confidence_score=0.98
    )
    db_session.add(recon_res)
    db_session.commit()
    assert recon_res.id is not None

    # 5. Create an ExceptionCandidate
    candidate = ExceptionCandidate(
        reconciliation_result_id=recon_res.id,
        order_ledger_id=ledger_rec.id
    )
    db_session.add(candidate)
    db_session.commit()
    assert candidate.id is not None

    # 6. Create a ReasoningCard
    card = ReasoningCard(
        reconciliation_result_id=recon_res.id,
        hypothesis_text="Shortfall matches 3% MDR fee + GST",
        calculation_breakdown='{"residual_gap": 0.00}',
        confidence_score=0.98,
        suggested_category="MDR_VARIANCE",
        requires_human_review=True
    )
    db_session.add(card)
    db_session.commit()
    assert card.id is not None

    # 7. Create an AuditLog entry
    audit = AuditLog(
        batch_id=batch.id,
        event_type=AuditEventType.llm_call,
        actor="llm",
        payload_json='{"event": "hypothesis_tested", "gap": 0.0}'
    )
    db_session.add(audit)
    db_session.commit()
    assert audit.id is not None

    # Verify UNIQUE(batch_id, settlement_record_id) idempotency constraint
    duplicate_recon = ReconciliationResult(
        batch_id=batch.id,
        settlement_record_id=settle_rec.id,
        status=ReconciliationStatus.exception_unresolved
    )
    db_session.add(duplicate_recon)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
