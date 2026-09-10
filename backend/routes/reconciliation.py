import json
from datetime import datetime, timezone
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, status
from sqlalchemy.orm import Session, joinedload, selectinload
from sqlalchemy import func
import uuid

from backend.database import get_db
from backend.models import (
    Batch,
    BatchStatus,
    ReconciliationResult,
    ReconciliationStatus,
    SettlementRecord,
    OrderLedger,
    ReasoningCard,
    ExceptionCandidate,
    AuditEventType
)
from backend.schemas import (
    MatchRunResponse,
    ExceptionsListResponse,
    ExceptionItemOut,
    SettlementRecordOut,
    OrderLedgerOut,
    ReasoningCardOut,
    ApproveRequest,
    ApproveResponse,
    RejectRequest,
    RejectResponse
)
from backend.matching import run_deterministic_matching
from backend.reasoning import run_batch_reasoning_pipeline
from backend.audit import log_audit_event
from backend.database import SessionLocal
from backend.security import verify_api_key

router = APIRouter(tags=["Reconciliation"])


@router.post("/batches/{batch_id}/run-matching", response_model=MatchRunResponse)
def trigger_matching(
    batch_id: uuid.UUID,
    api_key: Optional[str] = Depends(verify_api_key),
    db: Session = Depends(get_db)
):
    """Triggers synchronous deterministic matching engine pass."""
    batch = db.query(Batch).filter(Batch.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Batch not found")

    try:
        result = run_deterministic_matching(db=db, batch_id=batch_id)
        return MatchRunResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/batches/{batch_id}/run-reasoning", status_code=status.HTTP_202_ACCEPTED)
async def trigger_reasoning(
    batch_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    api_key: Optional[str] = Depends(verify_api_key),
    db: Session = Depends(get_db)
):
    """
    Triggers asynchronous LLM discrepancy reasoning pass on all exception records.
    Returns job_id immediately; frontend polls /batches/{id}/summary.
    """
    batch = db.query(Batch).filter(Batch.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Batch not found")

    job_id = uuid.uuid4()
    
    # Run async background pipeline
    background_tasks.add_task(run_batch_reasoning_pipeline, batch_id, SessionLocal)

    exception_count = db.query(func.count(ReconciliationResult.id)).filter(
        ReconciliationResult.batch_id == batch_id,
        ReconciliationResult.status == ReconciliationStatus.exception_unresolved
    ).scalar() or 0

    return {
        "batch_id": batch_id,
        "job_id": job_id,
        "exception_count": exception_count,
        "message": "Reasoning started. Poll /summary for completion status."
    }


@router.get("/batches/{batch_id}/exceptions", response_model=ExceptionsListResponse)
def list_exceptions(
    batch_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status_filter: Optional[str] = Query(None, alias="status"),
    db: Session = Depends(get_db)
):
    """Returns paginated reasoning cards and exception records for human review."""
    base_filter = [
        ReconciliationResult.batch_id == batch_id,
        ReconciliationResult.status.in_([
            ReconciliationStatus.exception_unresolved,
            ReconciliationStatus.matched_ai_resolved,
            ReconciliationStatus.human_approved,
            ReconciliationStatus.human_rejected
        ])
    ]

    if status_filter:
        try:
            parsed_status = ReconciliationStatus(status_filter)
            base_filter.append(ReconciliationResult.status == parsed_status)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid status filter '{status_filter}'."
            )

    # FIX A5: Separate count query from joinedload data query to prevent inflated / incorrect count
    total = db.query(func.count(ReconciliationResult.id)).filter(*base_filter).scalar() or 0

    # FIX H7: Eager-load all accessed relationships to eliminate N+1 queries per row
    results = db.query(ReconciliationResult).filter(*base_filter).options(
        joinedload(ReconciliationResult.settlement_record),
        joinedload(ReconciliationResult.order_ledger),
        joinedload(ReconciliationResult.reasoning_card),
        selectinload(ReconciliationResult.exception_candidates).joinedload(
            ExceptionCandidate.order_ledger
        )
    ).offset(offset).limit(limit).all()

    items = []
    for r in results:
        s = r.settlement_record
        settle_out = SettlementRecordOut(
            gateway_txn_id=s.gateway_txn_id,
            order_id=s.order_id,
            settled_amount=float(s.settled_amount),
            settlement_timestamp=s.settlement_timestamp,
            fee_deducted=float(s.fee_deducted) if s.fee_deducted is not None else None,
            currency=s.currency
        )

        candidate_orders_out = []
        if r.exception_candidates:
            for ec in r.exception_candidates:
                o = ec.order_ledger
                candidate_orders_out.append(OrderLedgerOut(
                    order_id=o.order_id,
                    billed_amount=float(o.billed_amount),
                    order_timestamp=o.order_timestamp,
                    refund_amount=float(o.refund_amount) if o.refund_amount is not None else None,
                    is_international=o.is_international,
                    payment_method=o.payment_method
                ))
        elif r.order_ledger:
            o = r.order_ledger
            candidate_orders_out.append(OrderLedgerOut(
                order_id=o.order_id,
                billed_amount=float(o.billed_amount),
                order_timestamp=o.order_timestamp,
                refund_amount=float(o.refund_amount) if o.refund_amount is not None else None,
                is_international=o.is_international,
                payment_method=o.payment_method
            ))

        card_out = None
        if r.reasoning_card:
            card = r.reasoning_card
            breakdown = (
                json.loads(card.calculation_breakdown)
                if isinstance(card.calculation_breakdown, str)
                else card.calculation_breakdown
            )
            card_out = ReasoningCardOut(
                id=card.id,
                hypothesis_text=card.hypothesis_text,
                calculation_breakdown=breakdown,
                confidence_score=float(card.confidence_score),
                suggested_category=card.suggested_category,
                requires_human_review=card.requires_human_review,
                human_override_note=card.human_override_note
            )

        items.append(ExceptionItemOut(
            reconciliation_result_id=r.id,
            settlement_record=settle_out,
            candidate_orders=candidate_orders_out if candidate_orders_out else None,
            discrepancy_amount=float(r.discrepancy_amount) if r.discrepancy_amount is not None else None,
            routing_reason=r.routing_reason.value if r.routing_reason else None,
            status=r.status.value,
            reasoning_card=card_out
        ))

    return ExceptionsListResponse(total=total, items=items)


@router.post("/reconciliation/{result_id}/approve", response_model=ApproveResponse)
def approve_reasoning_card(
    result_id: uuid.UUID,
    body: Optional[ApproveRequest] = None,
    api_key: Optional[str] = Depends(verify_api_key),
    db: Session = Depends(get_db)
):
    """
    Human approves an AI-resolved reasoning card.
    Enforces strict atomic guard: status must be 'matched_ai_resolved'.
    Prevents approving unexplained/unresolved cards.
    """
    reviewed_by = body.reviewed_by if body and body.reviewed_by else "accountant_user"
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # Atomic conditional update
    rows_updated = db.query(ReconciliationResult).filter(
        ReconciliationResult.id == result_id,
        ReconciliationResult.status == ReconciliationStatus.matched_ai_resolved
    ).update({
        ReconciliationResult.status: ReconciliationStatus.human_approved,
        ReconciliationResult.reviewed_at: now,
        ReconciliationResult.reviewed_by: reviewed_by
    }, synchronize_session="fetch")

    if rows_updated == 0:
        # Check if record was already actioned or is unresolved
        rec = db.query(ReconciliationResult).filter(ReconciliationResult.id == result_id).first()
        if not rec:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reconciliation result not found")
        if rec.status == ReconciliationStatus.human_approved:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This record has already been approved.")
        if rec.status == ReconciliationStatus.human_rejected:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This record has already been rejected.")
        if rec.status == ReconciliationStatus.exception_unresolved:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unresolved exceptions cannot be approved to post funds. Only AI-resolved records can be approved."
            )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This record has already been actioned.")

    # Fetch batch_id for audit logging
    recon = db.query(ReconciliationResult).filter(ReconciliationResult.id == result_id).first()

    # Log human_approval and journal_posted events
    log_audit_event(
        db=db,
        batch_id=recon.batch_id,
        event_type=AuditEventType.human_approval,
        actor=reviewed_by,
        payload={"result_id": str(result_id), "action": "approved"}
    )
    log_audit_event(
        db=db,
        batch_id=recon.batch_id,
        event_type=AuditEventType.journal_posted,
        actor="system",
        payload={"result_id": str(result_id), "status": "posted_to_ledger"}
    )

    db.commit()

    return ApproveResponse(
        result_id=result_id,
        status="human_approved",
        journal_posted=True,
        reviewed_at=now
    )


@router.post("/reconciliation/{result_id}/reject", response_model=RejectResponse)
def reject_reasoning_card(
    result_id: uuid.UUID,
    body: Optional[RejectRequest] = None,
    api_key: Optional[str] = Depends(verify_api_key),
    db: Session = Depends(get_db)
):
    """
    Human rejects a reasoning card or routes an unresolved exception to manual review.
    Atomic guard covers both 'matched_ai_resolved' and 'exception_unresolved'.
    """
    reviewed_by = body.reviewed_by if body and body.reviewed_by else "accountant_user"
    override_note = body.override_note if body else None
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    rows_updated = db.query(ReconciliationResult).filter(
        ReconciliationResult.id == result_id,
        ReconciliationResult.status.in_([
            ReconciliationStatus.matched_ai_resolved,
            ReconciliationStatus.exception_unresolved
        ])
    ).update({
        ReconciliationResult.status: ReconciliationStatus.human_rejected,
        ReconciliationResult.reviewed_at: now,
        ReconciliationResult.reviewed_by: reviewed_by
    }, synchronize_session="fetch")

    if rows_updated == 0:
        rec = db.query(ReconciliationResult).filter(ReconciliationResult.id == result_id).first()
        if not rec:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reconciliation result not found")
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This record has already been actioned.")

    recon = db.query(ReconciliationResult).filter(ReconciliationResult.id == result_id).first()

    # If override note provided, save to reasoning_card
    if override_note and recon.reasoning_card:
        recon.reasoning_card.human_override_note = override_note

    log_audit_event(
        db=db,
        batch_id=recon.batch_id,
        event_type=AuditEventType.human_rejection,
        actor=reviewed_by,
        payload={"result_id": str(result_id), "action": "rejected", "override_note": override_note}
    )

    db.commit()

    return RejectResponse(
        result_id=result_id,
        status="human_rejected",
        reviewed_at=now
    )
