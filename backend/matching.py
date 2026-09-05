from datetime import datetime, timedelta
from typing import Tuple, Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy import func
import uuid

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
    AuditEventType
)
from backend.audit import log_audit_event


def run_deterministic_matching(db: Session, batch_id: uuid.UUID) -> Dict[str, Any]:
    """
    Executes Step 1 Deterministic Matching Engine on a batch:
    - Primary pass: order_id match (unconditional trust, sanity check if fee_deducted present)
    - Fallback pass: fee-adjusted amount + timestamp (only if fee_deducted IS NOT NULL)
    - Exceptions: tags routing_reason (amount_mismatch, ambiguous_multiple, currency_mismatch, no_match)
    - Stores ambiguous multiple candidates in exception_candidates table
    - Updates batch status and match_rate_deterministic
    - Logs match audit events
    """
    batch = db.query(Batch).filter(Batch.id == batch_id).first()
    if not batch:
        raise ValueError("Batch not found")

    settlement_records = db.query(SettlementRecord).filter(SettlementRecord.batch_id == batch_id).all()
    ledger_records = db.query(OrderLedger).filter(OrderLedger.batch_id == batch_id).all()

    # Pre-index ledger records by order_id for fast O(1) lookups
    ledger_by_order_id: Dict[str, List[OrderLedger]] = {}
    for l in ledger_records:
        ledger_by_order_id.setdefault(l.order_id, []).append(l)

    tolerance_window = timedelta(seconds=batch.timestamp_tolerance_seconds)

    matched_count = 0
    exception_count = 0

    # Clear previous results if re-running (idempotent reset for matching)
    db.query(ReconciliationResult).filter(ReconciliationResult.batch_id == batch_id).delete()
    db.flush()

    for s in settlement_records:
        settled_amount = float(s.settled_amount)
        fee_deducted = float(s.fee_deducted) if s.fee_deducted is not None else None
        
        candidates: List[OrderLedger] = []
        came_from_order_id = False
        came_from_fallback = False

        # ── STEP 1: Primary Match on Order_ID ─────────────────────────────
        if s.order_id and s.order_id in ledger_by_order_id:
            candidates = ledger_by_order_id[s.order_id]
            came_from_order_id = True

        # ── STEP 2: Fallback on fee-adjusted amount + timestamp ───────────
        elif fee_deducted is not None:
            for l in ledger_records:
                expected_settled = float(l.billed_amount) - fee_deducted
                amount_diff = abs(expected_settled - settled_amount)
                time_diff = abs(l.order_timestamp - s.settlement_timestamp)
                
                if amount_diff < 0.01 and time_diff <= tolerance_window:
                    candidates.append(l)
            if candidates:
                came_from_fallback = True

        # ── STEP 3: Evaluation & Routing ──────────────────────────────────
        if len(candidates) == 1 and came_from_order_id:
            candidate = candidates[0]
            billed_amount = float(candidate.billed_amount)

            # Optional fee sanity check if fee_deducted is present
            if fee_deducted is not None:
                sanity_gap = abs(billed_amount - fee_deducted - settled_amount)
                if sanity_gap >= 0.01:
                    # Amount mismatch exception, but keep candidate order for LLM context
                    res = ReconciliationResult(
                        id=uuid.uuid4(),
                        batch_id=batch.id,
                        settlement_record_id=s.id,
                        order_ledger_id=candidate.id,
                        status=ReconciliationStatus.exception_unresolved,
                        routing_reason=RoutingReason.amount_mismatch,
                        discrepancy_amount=round(billed_amount - settled_amount, 2),
                        resolution_source=ResolutionSource.rule_engine
                    )
                    db.add(res)
                    exception_count += 1
                    continue

            # Deterministic Match
            discrepancy = round(billed_amount - settled_amount, 2)
            res = ReconciliationResult(
                id=uuid.uuid4(),
                batch_id=batch.id,
                settlement_record_id=s.id,
                order_ledger_id=candidate.id,
                status=ReconciliationStatus.matched_deterministic,
                routing_reason=RoutingReason.order_id_match,
                discrepancy_amount=discrepancy,
                resolution_source=ResolutionSource.rule_engine
            )
            db.add(res)
            matched_count += 1

        elif len(candidates) == 1 and came_from_fallback:
            candidate = candidates[0]
            billed_amount = float(candidate.billed_amount)
            discrepancy = round(billed_amount - settled_amount, 2)

            res = ReconciliationResult(
                id=uuid.uuid4(),
                batch_id=batch.id,
                settlement_record_id=s.id,
                order_ledger_id=candidate.id,
                status=ReconciliationStatus.matched_deterministic,
                routing_reason=RoutingReason.amount_match,
                discrepancy_amount=discrepancy,
                resolution_source=ResolutionSource.rule_engine
            )
            db.add(res)
            matched_count += 1

        else:
            # Exception Case
            exception_count += 1
            reason = RoutingReason.no_match
            if len(candidates) > 1:
                reason = RoutingReason.ambiguous_multiple
            elif s.currency != "INR":
                reason = RoutingReason.currency_mismatch

            res = ReconciliationResult(
                id=uuid.uuid4(),
                batch_id=batch.id,
                settlement_record_id=s.id,
                order_ledger_id=candidates[0].id if len(candidates) == 1 else None,
                status=ReconciliationStatus.exception_unresolved,
                routing_reason=reason,
                discrepancy_amount=None,
                resolution_source=ResolutionSource.rule_engine
            )
            db.add(res)
            db.flush()

            # Store multiple candidates in exception_candidates table
            if len(candidates) > 1:
                for cand in candidates:
                    db.add(ExceptionCandidate(
                        id=uuid.uuid4(),
                        reconciliation_result_id=res.id,
                        order_ledger_id=cand.id
                    ))

    # Update Batch stats
    total_records = len(settlement_records)
    match_rate = round((matched_count / total_records * 100.0), 2) if total_records > 0 else 0.0
    
    batch.status = BatchStatus.matching_complete
    batch.match_rate_deterministic = match_rate
    batch.unresolved_count = exception_count
    
    # Audit log entry for deterministic match pass
    log_audit_event(
        db=db,
        batch_id=batch.id,
        event_type=AuditEventType.match,
        actor="rule_engine",
        payload={
            "matched_deterministic_count": matched_count,
            "exception_count": exception_count,
            "match_rate_deterministic_pct": match_rate
        }
    )

    db.commit()
    db.refresh(batch)

    return {
        "batch_id": batch.id,
        "status": batch.status.value,
        "matched_deterministic_count": matched_count,
        "exception_count": exception_count,
        "match_rate_deterministic_pct": match_rate
    }
