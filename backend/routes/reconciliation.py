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
    ProposeRequest,
    ProposeResponse,
    AuthorizeRequest,
    AuthorizeResponse,
    RejectRequest,
    RejectResponse
)
from backend.matching import run_deterministic_matching
from backend.reasoning import run_batch_reasoning_pipeline
from backend.audit import log_audit_event
from backend.database import SessionLocal
from backend.security import verify_api_key

router = APIRouter(tags=["Reconciliation"])

MAKER_CHECKER_THRESHOLD = 10000.0  # Variances > ₹10,000 require two-party authorization


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
    Uses atomic conditional update to guarantee that duplicate concurrent requests cannot race.
    """
    updated_rows = db.query(Batch).filter(
        Batch.id == batch_id,
        Batch.status == BatchStatus.matching_complete
    ).update({
        Batch.status: BatchStatus.reasoning_in_progress
    }, synchronize_session="fetch")
    db.commit()

    if updated_rows == 0:
        batch = db.query(Batch).filter(Batch.id == batch_id).first()
        if not batch:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Batch not found")
        if batch.status == BatchStatus.reasoning_in_progress:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Reasoning is already in progress for this batch.")
        if batch.status == BatchStatus.reasoning_complete:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Reasoning has already been completed for this batch.")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Batch must be in matching_complete status before running reasoning (current: {batch.status.value})."
        )

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
            ReconciliationStatus.pending_authorization,
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

    total = db.query(func.count(ReconciliationResult.id)).filter(*base_filter).scalar() or 0

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
                suggested_category=card.suggested_category.value if hasattr(card.suggested_category, "value") else str(card.suggested_category),
                requires_human_review=card.requires_human_review,
                human_override_note=card.human_override_note
            )

        disc_amt = float(r.discrepancy_amount) if r.discrepancy_amount is not None else 0.0
        requires_mc = disc_amt > MAKER_CHECKER_THRESHOLD

        items.append(ExceptionItemOut(
            reconciliation_result_id=r.id,
            settlement_record=settle_out,
            candidate_orders=candidate_orders_out if candidate_orders_out else None,
            discrepancy_amount=disc_amt,
            routing_reason=r.routing_reason.value if r.routing_reason else None,
            status=r.status.value,
            requires_maker_checker=requires_mc or r.requires_maker_checker,
            proposed_by=r.proposed_by,
            authorized_by=r.authorized_by,
            reasoning_card=card_out
        ))

    return ExceptionsListResponse(total=total, items=items)


@router.post("/reconciliation/{result_id}/propose", response_model=ProposeResponse)
def propose_reconciliation(
    result_id: uuid.UUID,
    body: Optional[ProposeRequest] = None,
    api_key: Optional[str] = Depends(verify_api_key),
    db: Session = Depends(get_db)
):
    """
    Maker Step: An accountant proposes resolution on an AI-resolved card.
    Transitions status to 'pending_authorization' for two-party Maker-Checker review.
    """
    proposed_by = body.proposed_by if body and body.proposed_by else "accountant_maker"
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    rows_updated = db.query(ReconciliationResult).filter(
        ReconciliationResult.id == result_id,
        ReconciliationResult.status == ReconciliationStatus.matched_ai_resolved
    ).update({
        ReconciliationResult.status: ReconciliationStatus.pending_authorization,
        ReconciliationResult.proposed_by: proposed_by,
        ReconciliationResult.proposed_at: now,
        ReconciliationResult.requires_maker_checker: True
    }, synchronize_session="fetch")

    if rows_updated == 0:
        rec = db.query(ReconciliationResult).filter(ReconciliationResult.id == result_id).first()
        if not rec:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reconciliation result not found")
        if rec.status == ReconciliationStatus.pending_authorization:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This record is already proposed and pending authorization.")
        if rec.status in (ReconciliationStatus.human_approved, ReconciliationStatus.human_rejected):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This record has already been actioned.")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only AI-resolved records can be proposed.")

    recon = db.query(ReconciliationResult).filter(ReconciliationResult.id == result_id).first()

    log_audit_event(
        db=db,
        batch_id=recon.batch_id,
        event_type=AuditEventType.human_proposal,
        actor=proposed_by,
        payload={"result_id": str(result_id), "action": "proposed", "note": body.note if body else None}
    )

    db.commit()

    return ProposeResponse(
        result_id=result_id,
        status=ReconciliationStatus.pending_authorization.value,
        proposed_by=proposed_by,
        proposed_at=now,
        requires_maker_checker=True,
        message="Proposal recorded. Awaiting secondary controller authorization."
    )


@router.post("/reconciliation/{result_id}/authorize", response_model=AuthorizeResponse)
def authorize_reconciliation(
    result_id: uuid.UUID,
    body: Optional[AuthorizeRequest] = None,
    api_key: Optional[str] = Depends(verify_api_key),
    db: Session = Depends(get_db)
):
    """
    Checker Step: A secondary controller authorizes a proposed resolution.
    Enforces strict segregation of duties: Maker cannot authorize their own proposal (403 Forbidden).
    """
    authorized_by = body.authorized_by if body and body.authorized_by else "controller_checker"
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    rec = db.query(ReconciliationResult).filter(ReconciliationResult.id == result_id).first()
    if not rec:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reconciliation result not found")

    if rec.status != ReconciliationStatus.pending_authorization:
        if rec.status == ReconciliationStatus.human_approved:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This record has already been authorized.")
        if rec.status == ReconciliationStatus.human_rejected:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This record has already been rejected.")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Record is not in pending_authorization status (current: {rec.status.value}). Propose resolution first."
        )

    # 403 Forbidden on self-authorization (Maker == Checker)
    if rec.proposed_by and rec.proposed_by == authorized_by:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Maker-Checker violation: '{authorized_by}' proposed this resolution and cannot authorize their own proposal."
        )

    # Atomic update
    rows_updated = db.query(ReconciliationResult).filter(
        ReconciliationResult.id == result_id,
        ReconciliationResult.status == ReconciliationStatus.pending_authorization
    ).update({
        ReconciliationResult.status: ReconciliationStatus.human_approved,
        ReconciliationResult.authorized_by: authorized_by,
        ReconciliationResult.authorized_at: now,
        ReconciliationResult.reviewed_by: authorized_by,
        ReconciliationResult.reviewed_at: now
    }, synchronize_session="fetch")

    if rows_updated == 0:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Concurrency conflict: record state changed during authorization.")

    log_audit_event(
        db=db,
        batch_id=rec.batch_id,
        event_type=AuditEventType.human_approval,
        actor=authorized_by,
        payload={"result_id": str(result_id), "action": "authorized", "proposed_by": rec.proposed_by}
    )
    log_audit_event(
        db=db,
        batch_id=rec.batch_id,
        event_type=AuditEventType.journal_posted,
        actor="system",
        payload={"result_id": str(result_id), "status": "posted_to_ledger"}
    )

    db.commit()

    return AuthorizeResponse(
        result_id=result_id,
        status=ReconciliationStatus.human_approved.value,
        proposed_by=rec.proposed_by,
        authorized_by=authorized_by,
        journal_posted=True,
        authorized_at=now
    )


@router.post("/reconciliation/{result_id}/approve", response_model=ApproveResponse)
def approve_reasoning_card(
    result_id: uuid.UUID,
    body: Optional[ApproveRequest] = None,
    api_key: Optional[str] = Depends(verify_api_key),
    db: Session = Depends(get_db)
):
    """
    Standard single-user approval for low-to-medium variance discrepancies (<= ₹10,000).
    For high-value variances (> ₹10,000), initiates Maker-Checker proposal flow.
    """
    reviewed_by = body.reviewed_by if body and body.reviewed_by else "accountant_user"
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    rec = db.query(ReconciliationResult).filter(ReconciliationResult.id == result_id).first()
    if not rec:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reconciliation result not found")

    if rec.status == ReconciliationStatus.exception_unresolved:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unresolved exceptions cannot be approved to post funds. Only AI-resolved records can be approved."
        )

    if rec.status in (ReconciliationStatus.human_approved, ReconciliationStatus.human_rejected):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This record has already been actioned.")

    # High-value variance requires Maker-Checker flow
    disc_amount = float(rec.discrepancy_amount) if rec.discrepancy_amount is not None else 0.0
    if disc_amount > MAKER_CHECKER_THRESHOLD:
        # Move to pending_authorization
        rec.status = ReconciliationStatus.pending_authorization
        rec.proposed_by = reviewed_by
        rec.proposed_at = now
        rec.requires_maker_checker = True
        
        log_audit_event(
            db=db,
            batch_id=rec.batch_id,
            event_type=AuditEventType.human_proposal,
            actor=reviewed_by,
            payload={"result_id": str(result_id), "action": "proposed", "threshold_exceeded": True}
        )
        db.commit()

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Discrepancy (₹{disc_amount:,.2f}) exceeds ₹{MAKER_CHECKER_THRESHOLD:,.2f} threshold. "
                   f"Moved to 'pending_authorization'. Secondary controller must authorize via /authorize."
        )

    # Standard approval for <= threshold
    rows_updated = db.query(ReconciliationResult).filter(
        ReconciliationResult.id == result_id,
        ReconciliationResult.status == ReconciliationStatus.matched_ai_resolved
    ).update({
        ReconciliationResult.status: ReconciliationStatus.human_approved,
        ReconciliationResult.reviewed_at: now,
        ReconciliationResult.reviewed_by: reviewed_by
    }, synchronize_session="fetch")

    if rows_updated == 0:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This record has already been actioned.")

    log_audit_event(
        db=db,
        batch_id=rec.batch_id,
        event_type=AuditEventType.human_approval,
        actor=reviewed_by,
        payload={"result_id": str(result_id), "action": "approved"}
    )
    log_audit_event(
        db=db,
        batch_id=rec.batch_id,
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
    Atomic guard covers 'matched_ai_resolved', 'pending_authorization', and 'exception_unresolved'.
    """
    reviewed_by = body.reviewed_by if body and body.reviewed_by else "accountant_user"
    override_note = body.override_note if body else None
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    rows_updated = db.query(ReconciliationResult).filter(
        ReconciliationResult.id == result_id,
        ReconciliationResult.status.in_([
            ReconciliationStatus.matched_ai_resolved,
            ReconciliationStatus.pending_authorization,
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
