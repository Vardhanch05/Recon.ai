from datetime import datetime, timedelta
from typing import Tuple, Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy import func # SQLAlchemy SQL function helpers (e.g. func.abs for mathematical differences)
import uuid

try:
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
except ImportError:
    from models import (
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
    from audit import log_audit_event


# --- Deterministic Matching Engine (Rule-Based Pass ~80% Match Target) ---
def run_deterministic_matching(db: Session, batch_id: uuid.UUID) -> Dict[str, Any]:
    """
    Executes Step 1 Deterministic Matching Engine on a batch:
    1. Primary Pass: order_id match (O(1) hash map lookup).
       - If fee_deducted is present: runs a fee sanity check.
       - If sanity check fails -> routes to 'amount_mismatch' exception for LLM reasoner.
    2. Fallback Pass: fee-adjusted amount + timestamp window.
       - Activated when order_id is missing/unmatched and fee_deducted IS NOT NULL.
    3. Exception Routing:
       - Tags exceptions with routing_reason ('amount_mismatch', 'ambiguous_multiple', 'currency_mismatch', 'no_match').
       - If multiple orders match the fallback, persists them in exception_candidates table.
    4. Idempotency & Batch Metrics:
       - Clears previous results if re-running.
       - Updates batch status and match_rate_deterministic percentage.
       - Writes an immutable 'match' event to audit_log.
    """

    # 1. Fetch the target batch
    batch = db.query(Batch).filter(Batch.id == batch_id).first()
    if not batch:
        raise ValueError("Batch not found")

    # 2. Load all the settlement and ledger entries for this batch
    settlement_records = db.query(SettlementRecord).filter(SettlementRecord.batch_id == batch_id).all()
    ledger_records = db.query(OrderLedger).filter(OrderLedger.batch_id == batch_id).all()

    # Pre-index ledger records by order_id and rounded billed_amount for O(1) lookups
    ledger_by_order_id: Dict[str, List[OrderLedger]] = {}
    ledger_by_amount: Dict[float, List[OrderLedger]] = {}
    for l in ledger_records:
        ledger_by_order_id.setdefault(l.order_id, []).append(l)
        ledger_by_amount.setdefault(round(float(l.billed_amount), 2), []).append(l)

    # Define the time tolerance window for fallback matching
    tolerance_window = timedelta(seconds=batch.timestamp_tolerance_seconds)

    matched_count = 0
    exception_count = 0

    # Guard: Check if batch has any human_approved records before resetting
    approved_count = db.query(func.count(ReconciliationResult.id)).filter(
        ReconciliationResult.batch_id == batch_id,
        ReconciliationResult.status == ReconciliationStatus.human_approved
    ).scalar() or 0
    if approved_count > 0:
        raise ValueError("Cannot re-run matching on a batch that contains approved/posted records.")

    # Idempotency: Clear previous results if this batch is being re-run
    db.query(ReconciliationResult).filter(ReconciliationResult.batch_id == batch_id).delete()
    db.flush()

# --- Transaction Matching Loop ---
    for s in settlement_records:
        settled_amount = float(s.settled_amount)
        fee_deducted = float(s.fee_deducted) if s.fee_deducted is not None else None
        
        candidates: List[OrderLedger] = []
        came_from_order_id = False
        came_from_fallback = False

        # ---- Path A: Primary Match on Order_ID (Direct Reference Match) ----
        if s.order_id and s.order_id in ledger_by_order_id:
            candidates = ledger_by_order_id[s.order_id]
            came_from_order_id = True

        # ---- Path B: Fallback on fee-adjusted amount + timestamp window----
        # FIX A14: O(1) amount bucket lookup instead of full O(N*M) table scan
        elif fee_deducted is not None:
            expected_gross = round(settled_amount + fee_deducted, 2)
            potential_candidates = ledger_by_amount.get(expected_gross, [])
            for l in potential_candidates:
                time_diff = abs(l.order_timestamp - s.settlement_timestamp)
                if time_diff <= tolerance_window:
                    candidates.append(l)
            if candidates:
                came_from_fallback = True

        # ---- Path C: Evaluation & State Routing ----
        if len(candidates) == 1 and came_from_order_id:
            candidate = candidates[0]
            billed_amount = float(candidate.billed_amount)

            # Sanity Check: If fee was deducted, does gross - fee = net?
            if fee_deducted is not None:
                sanity_gap = abs(billed_amount - fee_deducted - settled_amount)
                if sanity_gap >= 0.01:
                    # Sanity gap failed -> Flag as exception, but link candidate order so AI can investigate
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

            # Deterministic Match Passed
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
            # ---- Path D: Ambiguous or Unmatched Exceptions ----
            exception_count += 1
            reason = RoutingReason.no_match
            if len(candidates) > 1:
                reason = RoutingReason.ambiguous_multiple
            elif s.currency and s.currency != "INR":
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

            # If multiple orders matched the fallback criteria, persist all candidates
            # into exception_candidates table so the AI Reasoner can choose between them
            if len(candidates) > 1:
                for cand in candidates:
                    db.add(ExceptionCandidate(
                        id=uuid.uuid4(),
                        reconciliation_result_id=res.id,
                        order_ledger_id=cand.id
                    ))

    # --- 4. Update Batch Metrics & Emit Audit Event --- 
    total_records = len(settlement_records)
    match_rate = round((matched_count / total_records * 100.0), 2) if total_records > 0 else 0.0
    
    batch.status = BatchStatus.matching_complete
    batch.matched_deterministic_count = matched_count
    batch.match_rate_deterministic = match_rate
    batch.unresolved_count = exception_count
    
    # Record the deterministic match pass in the immutable audit log
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
    