from datetime import datetime
from typing import Optional
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
import uuid

from backend.database import get_db
from backend.models import Batch, BatchStatus, SettlementRecord, OrderLedger, ReconciliationResult, ReconciliationStatus, AuditLog, AuditEventType
from backend.schemas import UploadResponse, BatchSummaryResponse, AuditLogResponse, AuditLogItemOut
from backend.ingestion import parse_settlement_csv, parse_ledger_csv
from backend.audit import log_audit_event

router = APIRouter(prefix="/batches", tags=["Batches"])

@router.post("/upload", response_model=UploadResponse, status_code=status.HTTP_200_OK)
async def upload_batch(
    settlement_file: UploadFile = File(..., description="Razorpay Settlement CSV file"),
    ledger_file: UploadFile = File(..., description="Merchant Internal Order Ledger CSV file"),
    timestamp_tolerance_seconds: int = Form(2, description="Tolerance in seconds for fallback matching"),
    confirm_overwrite: bool = Form(False, description="Overwrite if batch with identical filename exists"),
    db: Session = Depends(get_db)
):
    """
    Ingests settlement and ledger CSV files, creates a new batch,
    populates settlement_records and order_ledger, and logs any ingestion errors.
    """
    settlement_bytes = await settlement_file.read()
    ledger_bytes = await ledger_file.read()

    # Parse CSVs
    valid_settlements, settlement_errors = parse_settlement_csv(settlement_bytes)
    valid_ledgers, ledger_errors = parse_ledger_csv(ledger_bytes)

    total_ingestion_errors = len(settlement_errors) + len(ledger_errors)

    if not valid_settlements and not valid_ledgers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No valid rows could be parsed from the provided files."
        )

    # Create Batch record
    batch = Batch(
        id=uuid.uuid4(),
        uploaded_at=datetime.utcnow(),
        status=BatchStatus.uploaded,
        total_records=len(valid_settlements),
        ingestion_error_count=total_ingestion_errors,
        timestamp_tolerance_seconds=timestamp_tolerance_seconds
    )
    db.add(batch)
    db.flush()

    # Insert settlement records (skip intra-file duplicates if any)
    seen_gateway_txns = set()
    for row in valid_settlements:
        if row["gateway_txn_id"] in seen_gateway_txns:
            total_ingestion_errors += 1
            continue
        seen_gateway_txns.add(row["gateway_txn_id"])
        
        db.add(SettlementRecord(
            id=uuid.uuid4(),
            batch_id=batch.id,
            gateway_txn_id=row["gateway_txn_id"],
            order_id=row["order_id"],
            settled_amount=row["settled_amount"],
            settlement_timestamp=row["settlement_timestamp"],
            fee_deducted=row["fee_deducted"],
            currency=row["currency"],
            raw_row_json=row["raw_row_json"]
        ))

    # Insert order ledger records
    for row in valid_ledgers:
        db.add(OrderLedger(
            id=uuid.uuid4(),
            batch_id=batch.id,
            order_id=row["order_id"],
            billed_amount=row["billed_amount"],
            order_timestamp=row["order_timestamp"],
            refund_amount=row["refund_amount"],
            is_international=row["is_international"],
            payment_method=row["payment_method"],
            raw_row_json=row["raw_row_json"]
        ))

    # Log ingestion errors to audit log if any occurred
    if settlement_errors or ledger_errors:
        log_audit_event(
            db=db,
            batch_id=batch.id,
            event_type=AuditEventType.ingestion_error,
            actor="system",
            payload={
                "settlement_errors_count": len(settlement_errors),
                "ledger_errors_count": len(ledger_errors),
                "settlement_errors": settlement_errors[:10],
                "ledger_errors": ledger_errors[:10]
            }
        )

    batch.total_records = len(seen_gateway_txns)
    batch.ingestion_error_count = total_ingestion_errors
    db.commit()
    db.refresh(batch)

    return UploadResponse(
        batch_id=batch.id,
        total_records=batch.total_records,
        ingestion_error_count=batch.ingestion_error_count,
        status=batch.status.value
    )


@router.get("/{batch_id}/summary", response_model=BatchSummaryResponse)
def get_batch_summary(batch_id: uuid.UUID, db: Session = Depends(get_db)):
    """Returns batch pipeline status and match rate breakdown."""
    batch = db.query(Batch).filter(Batch.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Batch not found")

    matched_det = db.query(func.count(ReconciliationResult.id)).filter(
        ReconciliationResult.batch_id == batch_id,
        ReconciliationResult.status == ReconciliationStatus.matched_deterministic
    ).scalar() or 0

    matched_ai = db.query(func.count(ReconciliationResult.id)).filter(
        ReconciliationResult.batch_id == batch_id,
        ReconciliationResult.status.in_([
            ReconciliationStatus.matched_ai_resolved,
            ReconciliationStatus.human_approved
        ])
    ).scalar() or 0

    unresolved = db.query(func.count(ReconciliationResult.id)).filter(
        ReconciliationResult.batch_id == batch_id,
        ReconciliationResult.status.in_([
            ReconciliationStatus.exception_unresolved,
            ReconciliationStatus.human_rejected
        ])
    ).scalar() or 0

    return BatchSummaryResponse(
        batch_id=batch.id,
        status=batch.status.value,
        total_records=batch.total_records or 0,
        matched_deterministic_count=matched_det,
        matched_ai_resolved_count=matched_ai,
        unresolved_count=unresolved,
        ingestion_error_count=batch.ingestion_error_count,
        match_rate_deterministic_pct=float(batch.match_rate_deterministic) if batch.match_rate_deterministic is not None else None,
        match_rate_ai_resolved_pct=float(batch.match_rate_ai_resolved_pct) if hasattr(batch, 'match_rate_ai_resolved_pct') and batch.match_rate_ai_resolved is not None else (float(batch.match_rate_ai_resolved) if batch.match_rate_ai_resolved is not None else None),
        throughput_ms=getattr(batch, "throughput_ms", None)
    )


@router.get("/{batch_id}/audit-log", response_model=AuditLogResponse)
def get_batch_audit_log(
    batch_id: uuid.UUID,
    event_type: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Returns immutable audit events for a batch, optionally filtered by event_type."""
    query = db.query(AuditLog).filter(AuditLog.batch_id == batch_id)
    if event_type:
        query = query.filter(AuditLog.event_type == AuditEventType(event_type))
    
    events = query.order_by(AuditLog.timestamp.asc()).all()

    import json
    parsed_events = []
    for e in events:
        try:
            payload = json.loads(e.payload_json) if isinstance(e.payload_json, str) else e.payload_json
        except Exception:
            payload = {"raw": str(e.payload_json)}
            
        parsed_events.append(AuditLogItemOut(
            id=e.id,
            batch_id=e.batch_id,
            event_type=e.event_type.value,
            actor=e.actor,
            payload_json=payload,
            timestamp=e.timestamp
        ))

    return AuditLogResponse(
        total=len(parsed_events),
        events=parsed_events
    )
