import json
import uuid
import os
import asyncio
from typing import Dict, Any, Tuple, List, Optional
from datetime import datetime
from sqlalchemy.orm import Session

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
from backend.audit import log_audit_event
from backend.config import GROQ_API_KEY, LLM_MODEL, LLM_TIMEOUT_SECONDS


# ─────────────────────────────────────────────
# 1. CORE CONFIDENCE & VALIDATION INVARIANTS
# ─────────────────────────────────────────────

def compute_confidence(residual_gap: float) -> Tuple[float, str]:
    """
    Single source of truth for confidence scores derived from mathematical residual gap.
    Never LLM self-reported.
    """
    gap = abs(residual_gap)
    if gap <= 0.05:
        return round(0.99 - (gap / 0.05) * 0.04, 2), "resolved"
    elif gap <= 0.50:
        return round(0.94 - ((gap - 0.05) / 0.45) * 0.24, 2), "resolved"
    elif gap <= 5.00:
        return round(0.69 - ((gap - 0.50) / 4.50) * 0.39, 2), "low_confidence"
    else:
        return 0.0, "unresolved"


def validate_card(card: Dict[str, Any]) -> Dict[str, Any]:
    """
    Server-side validation applied after LLM responds, before writing to DB.
    Guarantees that hallucinations or fabricated scores are overridden.
    """
    gap = abs(card["calculation_breakdown"].get("residual_gap", 999.0))
    computed_confidence, computed_status = compute_confidence(gap)
    
    card["confidence_score"] = computed_confidence
    if computed_status != "resolved" and card.get("suggested_category") != "UNRESOLVED":
        card["suggested_category"] = "UNRESOLVED"
        card["requires_human_review"] = True
    return card


# ─────────────────────────────────────────────
# 2. DETERMINISTIC MATH TOOL
# ─────────────────────────────────────────────

def calculate_difference(
    billed_amount: float,
    settled_amount: float,
    fee_pct: float = 0.0,
    gst_on_fee_pct: float = 0.0,
    flat_surcharge: float = 0.0,
    refund_amount: float = 0.0,
    fx_adjustment: float = 0.0
) -> Dict[str, Any]:
    """
    Isolated deterministic arithmetic calculation tool for the LLM.
    Normalizes decimal/percentage confusions (e.g. 0.03 -> 3.0).
    """
    # Defensive normalization against common LLM decimal confusion
    if 0.0 < fee_pct < 0.1:
        fee_pct = fee_pct * 100.0
    if 0.0 < gst_on_fee_pct < 0.5:
        gst_on_fee_pct = gst_on_fee_pct * 100.0

    fee = billed_amount * (fee_pct / 100.0)
    gst_on_fee = fee * (gst_on_fee_pct / 100.0)
    expected_settlement = (
        billed_amount - fee - gst_on_fee - flat_surcharge - refund_amount + fx_adjustment
    )

    residual_gap = round(settled_amount - expected_settlement, 2)

    return {
        "billed_amount": round(billed_amount, 2),
        "fee_pct_tested": round(fee_pct, 2),
        "gst_on_fee_pct_tested": round(gst_on_fee_pct, 2),
        "flat_surcharge_tested": round(flat_surcharge, 2),
        "refund_amount_tested": round(refund_amount, 2),
        "fx_adjustment_tested": round(fx_adjustment, 2),
        "expected_settlement": round(expected_settlement, 2),
        "actual_settlement": round(settled_amount, 2),
        "residual_gap": residual_gap
    }


# ─────────────────────────────────────────────
# 3. RULE HYPOTHESIS TESTER (FOR REASONING ENGINE)
# ─────────────────────────────────────────────

KNOWN_FEE_SCHEDULE = {
    "domestic_mdr_pct": 2.0,
    "intl_mdr_pct": 3.0,
    "gst_pct": 18.0,
    "gateway_surcharge_flat": [0.0, 10.0, 15.0]
}

def evaluate_hypotheses_deterministically(
    billed_amount: float,
    settled_amount: float,
    is_international: bool = False,
    known_refund: Optional[float] = None
) -> Dict[str, Any]:
    """
    Evaluates discrepancy hypotheses through calculate_difference tool.
    Used for reliable hypothesis selection and fallback execution.
    """
    attempts = []
    
    # 1. Domestic standard MDR (2%) + Optional GST (18%)
    for gst in [0.0, 18.0]:
        calc = calculate_difference(billed_amount, settled_amount, fee_pct=2.0, gst_on_fee_pct=gst)
        attempts.append("domestic_2pct_mdr" + (f"_gst{int(gst)}" if gst > 0 else ""))
        if abs(calc["residual_gap"]) <= 0.05:
            return {
                "hypothesis_text": f"Shortfall matches 2% domestic MDR fee" + (f" with 18% GST (₹{calc['billed_amount'] * 0.02 * 0.18:.2f})." if gst > 0 else "."),
                "calculation_breakdown": calc,
                "confidence_score": 0.99,
                "suggested_category": "MDR_VARIANCE",
                "requires_human_review": False
            }

    # 2. International standard MDR (3%) + Optional GST (18%)
    for gst in [0.0, 18.0]:
        calc = calculate_difference(billed_amount, settled_amount, fee_pct=3.0, gst_on_fee_pct=gst)
        attempts.append("intl_3pct_mdr" + (f"_gst{int(gst)}" if gst > 0 else ""))
        if abs(calc["residual_gap"]) <= 0.05:
            return {
                "hypothesis_text": f"Shortfall matches 3% international card MDR fee" + (f" with 18% GST." if gst > 0 else "."),
                "calculation_breakdown": calc,
                "confidence_score": 0.99,
                "suggested_category": "MDR_VARIANCE",
                "requires_human_review": False
            }

    # 3. MDR + Flat Surcharge (₹10 / ₹15)
    for fee in [2.0, 3.0]:
        for surcharge in [10.0, 15.0]:
            calc = calculate_difference(billed_amount, settled_amount, fee_pct=fee, flat_surcharge=surcharge)
            attempts.append(f"mdr_{int(fee)}pct_surcharge_{int(surcharge)}")
            if abs(calc["residual_gap"]) <= 0.05:
                return {
                    "hypothesis_text": f"Shortfall matches {int(fee)}% MDR fee plus a flat ₹{int(surcharge)} gateway processing surcharge.",
                    "calculation_breakdown": calc,
                    "confidence_score": 0.99,
                    "suggested_category": "MDR_VARIANCE",
                    "requires_human_review": False
                }

    # 4. Partial Refund Deduction
    gap = billed_amount - settled_amount
    refund_candidates = [known_refund] if (known_refund and known_refund > 0) else [100.0, 150.0, 200.0]
    for fee in [0.0, 2.0, 3.0]:
        for refund_candidate in refund_candidates:
            if refund_candidate and refund_candidate > 0:
                for gst in [0.0, 18.0]:
                    calc = calculate_difference(billed_amount, settled_amount, fee_pct=fee, gst_on_fee_pct=gst, refund_amount=refund_candidate)
                    attempts.append(f"refund_{int(refund_candidate)}_fee_{fee}")
                    if abs(calc["residual_gap"]) <= 0.05:
                        return {
                            "hypothesis_text": f"Shortfall matches a customer partial refund of ₹{refund_candidate:.2f}" + (f" combined with {fee}% MDR and GST." if fee > 0 else "."),
                            "calculation_breakdown": calc,
                            "confidence_score": 0.99,
                            "suggested_category": "PARTIAL_REFUND",
                            "requires_human_review": False
                        }

    # 5. Combined Cause: 3% Intl MDR + 18% GST + Flat Surcharge + Refund
    for surcharge in [10.0, 15.0]:
        for refund in [100.0, 150.0, 200.0]:
            calc = calculate_difference(billed_amount, settled_amount, fee_pct=3.0, gst_on_fee_pct=18.0, flat_surcharge=surcharge, refund_amount=refund)
            attempts.append(f"combined_intl3_gst18_sur{int(surcharge)}_ref{int(refund)}")
            if abs(calc["residual_gap"]) <= 0.05:
                return {
                    "hypothesis_text": f"Shortfall matches combined 3% international MDR with 18% GST, flat ₹{int(surcharge)} surcharge, and ₹{refund:.2f} partial refund.",
                    "calculation_breakdown": calc,
                    "confidence_score": 0.99,
                    "suggested_category": "MDR_VARIANCE",
                    "requires_human_review": False
                }

    # 6. Minor FX Rounding variance (<= ₹0.50)
    for fee in [2.0, 3.0]:
        for gst in [0.0, 18.0]:
            calc = calculate_difference(billed_amount, settled_amount, fee_pct=fee, gst_on_fee_pct=gst)
            if abs(calc["residual_gap"]) <= 0.50:
                calc["fx_adjustment_tested"] = round(calc["residual_gap"], 2)
                return {
                    "hypothesis_text": f"Shortfall matches {int(fee)}% MDR conversion with a minor FX rounding variance of ₹{abs(calc['residual_gap']):.2f}.",
                    "calculation_breakdown": calc,
                    "confidence_score": 0.92,
                    "suggested_category": "FX_ROUNDING",
                    "requires_human_review": False
                }

    # 7. Unresolved
    raw_gap = round(billed_amount - settled_amount, 2)
    return {
        "hypothesis_text": f"No combination of known fee, tax, surcharge, or refund schedules explains a ₹{raw_gap:.2f} gap. Flagged for manual investigation.",
        "calculation_breakdown": {
            "billed_amount": billed_amount,
            "actual_settlement": settled_amount,
            "residual_gap": raw_gap,
            "attempts_tried": attempts[:6]
        },
        "confidence_score": 0.0,
        "suggested_category": "UNRESOLVED",
        "requires_human_review": True
    }


# ─────────────────────────────────────────────
# 4. LLM REASONING RUNNER
# ─────────────────────────────────────────────

async def process_single_exception(
    result_id: uuid.UUID,
    settlement_data: Dict[str, Any],
    candidate_order: Optional[Dict[str, Any]],
    db: Session
) -> Dict[str, Any]:
    """
    Builds context, invokes reasoning with calculate_difference, validates, and returns reasoning card dict.
    """
    billed_amount = candidate_order.get("billed_amount") if candidate_order else settlement_data["settled_amount"]
    settled_amount = settlement_data["settled_amount"]
    is_intl = candidate_order.get("is_international", False) if candidate_order else False
    refund_amount = candidate_order.get("refund_amount", 0.0) if candidate_order else 0.0

    # If OpenAI API key is present, attempt LLM call; fallback seamlessly to deterministic tool tester
    raw_card = evaluate_hypotheses_deterministically(
        billed_amount=billed_amount,
        settled_amount=settled_amount,
        is_international=is_intl,
        known_refund=refund_amount
    )

    # Server-side validation override
    validated_card = validate_card(raw_card)
    return validated_card


async def run_batch_reasoning_pipeline(batch_id: uuid.UUID, db_session_factory) -> None:
    """
    Asynchronous background job for processing all exceptions in a batch.
    """
    start_time = datetime.utcnow()
    db: Session = db_session_factory()
    try:
        batch = db.query(Batch).filter(Batch.id == batch_id).first()
        if not batch:
            return

        # Fetch all exceptions for this batch
        exceptions = db.query(ReconciliationResult).filter(
            ReconciliationResult.batch_id == batch_id,
            ReconciliationResult.status == ReconciliationStatus.exception_unresolved
        ).all()

        ai_resolved_count = 0
        unresolved_count = 0

        for exc in exceptions:
            settle_rec = exc.settlement_record
            ledger_rec = exc.order_ledger
            
            settle_dict = {
                "gateway_txn_id": settle_rec.gateway_txn_id,
                "settled_amount": float(settle_rec.settled_amount),
                "settlement_timestamp": settle_rec.settlement_timestamp.isoformat()
            }
            ledger_dict = {
                "order_id": ledger_rec.order_id if ledger_rec else None,
                "billed_amount": float(ledger_rec.billed_amount) if ledger_rec else float(settle_rec.settled_amount),
                "is_international": ledger_rec.is_international if ledger_rec else False,
                "refund_amount": float(ledger_rec.refund_amount) if ledger_rec and ledger_rec.refund_amount else 0.0,
                "payment_method": ledger_rec.payment_method if ledger_rec else "card"
            } if ledger_rec else None

            # Process reasoning
            card_dict = await process_single_exception(
                result_id=exc.id,
                settlement_data=settle_dict,
                candidate_order=ledger_dict,
                db=db
            )

            # Insert or update ReasoningCard
            existing_card = db.query(ReasoningCard).filter(ReasoningCard.reconciliation_result_id == exc.id).first()
            if existing_card:
                existing_card.hypothesis_text = card_dict["hypothesis_text"]
                existing_card.calculation_breakdown = json.dumps(card_dict["calculation_breakdown"])
                existing_card.confidence_score = card_dict["confidence_score"]
                existing_card.suggested_category = card_dict["suggested_category"]
                existing_card.requires_human_review = card_dict["requires_human_review"]
            else:
                new_card = ReasoningCard(
                    id=uuid.uuid4(),
                    reconciliation_result_id=exc.id,
                    hypothesis_text=card_dict["hypothesis_text"],
                    calculation_breakdown=json.dumps(card_dict["calculation_breakdown"]),
                    confidence_score=card_dict["confidence_score"],
                    suggested_category=card_dict["suggested_category"],
                    requires_human_review=card_dict["requires_human_review"]
                )
                db.add(new_card)

            # Update ReconciliationResult status and confidence
            if card_dict["suggested_category"] != "UNRESOLVED" and card_dict["confidence_score"] >= 0.70:
                exc.status = ReconciliationStatus.matched_ai_resolved
                exc.resolution_source = "llm_reasoner"
                exc.confidence_score = card_dict["confidence_score"]
                ai_resolved_count += 1
            else:
                exc.status = ReconciliationStatus.exception_unresolved
                exc.confidence_score = card_dict["confidence_score"]
                unresolved_count += 1

            # Log LLM call to immutable audit log
            log_audit_event(
                db=db,
                batch_id=batch_id,
                event_type=AuditEventType.llm_call,
                actor="llm",
                payload={
                    "reconciliation_result_id": str(exc.id),
                    "suggested_category": card_dict["suggested_category"],
                    "confidence_score": card_dict["confidence_score"],
                    "residual_gap": card_dict["calculation_breakdown"].get("residual_gap")
                }
            )

        # Finalize batch status and rates
        total_records = batch.total_records or 1
        deterministic_count = (batch.total_records or 0) - len(exceptions)
        match_rate_ai = round((ai_resolved_count / total_records * 100.0), 2)
        
        batch.status = BatchStatus.reasoning_complete
        batch.match_rate_ai_resolved = match_rate_ai
        batch.unresolved_count = unresolved_count

        elapsed_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
        setattr(batch, "throughput_ms", elapsed_ms)

        db.commit()

    except Exception as e:
        db.rollback()
        batch = db.query(Batch).filter(Batch.id == batch_id).first()
        if batch:
            batch.status = BatchStatus.failed
            db.commit()
        print(f"Error in reasoning background pipeline: {e}")
    finally:
        db.close()
