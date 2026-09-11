import json
import uuid
import os
import logging
import asyncio
from typing import Dict, Any, Tuple, List, Optional
from datetime import datetime, timezone
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
    AuditEventType,
    ResolutionSource,
    DiscrepancyCategory
)
from backend.audit import log_audit_event
from backend.config import GROQ_API_KEY, LLM_MODEL, LLM_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)


# --- 1. CORE CONFIDENCE & VALIDATION INVARIANTS ---

def compute_confidence(residual_gap: float) -> Tuple[float, str]:
    """
    Mathematical single source of truth for confidence scores.
    NEVER relies on self-reported LLM confidence to prevent hallucinated scores.
    
    Formula:
      • gap <= 0.05 (<= 5 paise):  Score 0.95 to 0.99 -> 'resolved'
      • gap <= 0.50 (<= 50 paise): Score 0.70 to 0.94 -> 'resolved' (minor FX/rounding)
      • gap <= 5.00:              Score 0.30 to 0.69 -> 'low_confidence'
      • gap > 5.00:               Score 0.00         -> 'unresolved'
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
    
    # Overwrite card confidence with server-computed value
    card["confidence_score"] = computed_confidence
    if computed_status != "resolved" and card.get("suggested_category") != "UNRESOLVED":
        card["suggested_category"] = "UNRESOLVED"
        card["requires_human_review"] = True
    return card


# --- 2. DETERMINISTIC MATH TOOL (Zero Hallucination Arithmetic) ---

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
    Isolated deterministic arithmetic calculation tool.
    LLMs are prohibited from doing mental math; they must call this tool.

    All fee/tax arguments MUST be supplied as percentage values (e.g., 2.0 for 2%).
    No silent normalization is performed — callers are responsible for correct units.

    Formula:
      fee = billed_amount * (fee_pct / 100)
      gst = fee * (gst_on_fee_pct / 100)
      expected_settlement = billed - fee - gst - flat_surcharge - refund + fx_adjustment
      residual_gap = settled_amount - expected_settlement
    """
    # FIX H6: Removed silent normalization (was multiplying sub-0.1% fees by 100x,
    # which would corrupt legitimate low-MDR tiers like UPI 0.09%). Inputs must
    # be supplied as explicit percentage values by the caller.
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


# --- 3. RULE HYPOTHESIS TESTER (FOR REASONING ENGINE) ---

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
    Evaluates known discrepancy hypotheses through calculate_difference.
    Tests:
      1. Domestic 2% MDR (+ optional 18% GST)
      2. International 3% MDR (+ optional 18% GST)
      3. Partial Refund deduction
      4. Flat Gateway Surcharges (₹10, ₹15)
      5. Combined causes (MDR + GST + Refund)
      6. FX Rounding (<= ₹0.50)
      7. UNRESOLVED (if residual gap remains)
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

    # 4. Partial Refund Deduction (evaluated when order ledger indicates a known refund)
    if known_refund and known_refund > 0:
        for fee in [0.0, 2.0, 3.0]:
            for gst in [0.0, 18.0]:
                calc = calculate_difference(billed_amount, settled_amount, fee_pct=fee, gst_on_fee_pct=gst, refund_amount=known_refund)
                attempts.append(f"refund_{int(known_refund)}_fee_{fee}")
                if abs(calc["residual_gap"]) <= 0.05:
                    return {
                        "hypothesis_text": f"Shortfall matches a customer partial refund of ₹{known_refund:.2f}" + (f" combined with {fee}% MDR and GST." if fee > 0 else "."),
                        "calculation_breakdown": calc,
                        "confidence_score": 0.99,
                        "suggested_category": DiscrepancyCategory.PARTIAL_REFUND.value,
                        "requires_human_review": False
                    }

    # 5. Combined Cause: 3% Intl MDR + 18% GST + Flat Surcharge (+ Optional Known Refund)
    for surcharge in [10.0, 15.0]:
        refund_val = known_refund if (known_refund and known_refund > 0) else 0.0
        calc = calculate_difference(billed_amount, settled_amount, fee_pct=3.0, gst_on_fee_pct=18.0, flat_surcharge=surcharge, refund_amount=refund_val)
        attempts.append(f"combined_intl3_gst18_sur{int(surcharge)}_ref{int(refund_val)}")
        if abs(calc["residual_gap"]) <= 0.05:
            text = f"Shortfall matches combined 3% international MDR with 18% GST and flat ₹{int(surcharge)} surcharge"
            if refund_val > 0:
                text += f", and ₹{refund_val:.2f} partial refund."
            else:
                text += "."
            return {
                "hypothesis_text": text,
                "calculation_breakdown": calc,
                "confidence_score": 0.99,
                "suggested_category": DiscrepancyCategory.MDR_VARIANCE.value,
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
                    "suggested_category": DiscrepancyCategory.FX_ROUNDING.value,
                    "requires_human_review": False
                }

    # 7. Unresolved anomaly
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
        "suggested_category": DiscrepancyCategory.UNRESOLVED.value,
        "requires_human_review": True
    }


# --- 4. ASYNC REASONING BACKGROUND PIPELINE FOR DISCREPANCIES --- 

import urllib.request
import urllib.error

async def call_groq_llm(
    billed_amount: float,
    settled_amount: float,
    is_international: bool,
    refund_amount: float
) -> Optional[Dict[str, Any]]:
    """
    Attempts calling Groq LLM API with structured reasoning when GROQ_API_KEY is configured.
    Enforces deterministic tool calculation for arithmetic verification.
    """
    if not GROQ_API_KEY:
        return None

    prompt = f"""You are a financial discrepancy reasoning engine for Razorpay settlements.
Billed Amount: {billed_amount}
Settled Amount: {settled_amount}
Is International: {is_international}
Refund Amount: {refund_amount}

Test standard fee schedules:
- Domestic MDR 2% (+ optional 18% GST on fee)
- International MDR 3% (+ optional 18% GST on fee)
- Flat Gateway Surcharges (₹10, ₹15)
- Partial Refund deductions
- FX Rounding (<= ₹0.50)

Respond strictly with valid JSON only in this schema:
{{
  "hypothesis_text": "description",
  "suggested_category": "MDR_VARIANCE|PARTIAL_REFUND|FX_ROUNDING|UNRESOLVED",
  "fee_pct": 2.0,
  "gst_on_fee_pct": 18.0,
  "flat_surcharge": 0.0,
  "refund_amount": 0.0,
  "fx_adjustment": 0.0
}}"""

    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": "You are a financial settlement reconciler. Output strictly valid JSON."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"}
    }

    try:
        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
                "User-Agent": "ReconAI/1.0"
            },
            method="POST"
        )
        loop = asyncio.get_event_loop()
        def _execute_req():
            with urllib.request.urlopen(req, timeout=LLM_TIMEOUT_SECONDS) as response:
                return response.read()

        res_bytes = await loop.run_in_executor(None, _execute_req)
        res_json = json.loads(res_bytes.decode("utf-8"))
        content = res_json["choices"][0]["message"]["content"]
        parsed = json.loads(content)

        # Run math through isolated deterministic tool
        calc = calculate_difference(
            billed_amount=billed_amount,
            settled_amount=settled_amount,
            fee_pct=float(parsed.get("fee_pct", 0.0)),
            gst_on_fee_pct=float(parsed.get("gst_on_fee_pct", 0.0)),
            flat_surcharge=float(parsed.get("flat_surcharge", 0.0)),
            refund_amount=float(parsed.get("refund_amount", 0.0)),
            fx_adjustment=float(parsed.get("fx_adjustment", 0.0))
        )
        return {
            "hypothesis_text": parsed.get("hypothesis_text", "LLM reasoning hypothesis."),
            "calculation_breakdown": calc,
            "suggested_category": parsed.get("suggested_category", "UNRESOLVED"),
            "confidence_score": 0.0,
            "requires_human_review": True
        }
    except Exception as e:
        logger.warning(f"Groq LLM call skipped/failed: {e}")
        return None


async def process_single_exception(
    result_id: uuid.UUID,
    settlement_data: Dict[str, Any],
    candidate_order: Optional[Dict[str, Any]],
    db: Session
) -> Tuple[Dict[str, Any], str]:
    """
    Builds context, invokes LLM/rule hypothesis testing, applies server-side validate_card override,
    and returns (validated_card, actor).
    """
    if not candidate_order:
        # No candidate order found to match against. Return UNRESOLVED card with 0 confidence immediately.
        unresolved_card = {
            "hypothesis_text": "No candidate order ledger entry found to reconcile against.",
            "calculation_breakdown": {
                "billed_amount": None,
                "actual_settlement": settlement_data["settled_amount"],
                "residual_gap": settlement_data["settled_amount"]
            },
            "confidence_score": 0.0,
            "suggested_category": DiscrepancyCategory.UNRESOLVED.value,
            "requires_human_review": True
        }
        return unresolved_card, "rule_reasoner"

    billed_amount = candidate_order["billed_amount"]
    settled_amount = settlement_data["settled_amount"]
    is_intl = candidate_order.get("is_international", False)
    refund_amount = candidate_order.get("refund_amount", 0.0)

    raw_card = None
    actor = "rule_reasoner"

    # Attempt LLM call if API key configured
    if GROQ_API_KEY:
        raw_card = await call_groq_llm(billed_amount, settled_amount, is_intl, refund_amount)
        if raw_card:
            actor = "llm"

    # Fallback seamlessly to deterministic rule engine
    if not raw_card:
        raw_card = evaluate_hypotheses_deterministically(
            billed_amount=billed_amount,
            settled_amount=settled_amount,
            is_international=is_intl,
            known_refund=refund_amount
        )
        actor = "rule_reasoner"

    # Server-side validation override
    validated_card = validate_card(raw_card)
    return validated_card, actor


async def run_batch_reasoning_pipeline(batch_id: uuid.UUID, db_session_factory) -> None:
    """
    Asynchronous background worker for processing all unresolved exceptions in a batch.
    Generates ReasoningCard rows, updates batch stats, and emits audit events.
    """
    start_time = datetime.now(timezone.utc).replace(tzinfo=None)
    db: Session = db_session_factory()
    COMMIT_BATCH_SIZE = 10
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
        processed_count = 0

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
                "billed_amount": float(ledger_rec.billed_amount) if ledger_rec else None,
                "is_international": ledger_rec.is_international if ledger_rec else False,
                "refund_amount": float(ledger_rec.refund_amount) if ledger_rec and ledger_rec.refund_amount else 0.0,
                "payment_method": ledger_rec.payment_method if ledger_rec else "card"
            } if ledger_rec else None

            # Process reasoning with isolated math
            card_dict, actor = await process_single_exception(
                result_id=exc.id,
                settlement_data=settle_dict,
                candidate_order=ledger_dict,
                db=db
            )

            # Insert or update ReasoningCard in DB
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

            # Update ReconciliationResult status based on validated confidence
            if card_dict["suggested_category"] != "UNRESOLVED" and card_dict["confidence_score"] >= 0.70:
                exc.status = ReconciliationStatus.matched_ai_resolved
                exc.resolution_source = ResolutionSource.llm_reasoner if actor == "llm" else ResolutionSource.rule_engine
                exc.confidence_score = card_dict["confidence_score"]
                ai_resolved_count += 1
            else:
                exc.status = ReconciliationStatus.exception_unresolved
                exc.confidence_score = card_dict["confidence_score"]
                unresolved_count += 1

            # Truthful audit actor
            log_audit_event(
                db=db,
                batch_id=batch_id,
                event_type=AuditEventType.llm_call,
                actor=actor,
                payload={
                    "reconciliation_result_id": str(exc.id),
                    "suggested_category": card_dict["suggested_category"],
                    "confidence_score": card_dict["confidence_score"],
                    "residual_gap": card_dict["calculation_breakdown"].get("residual_gap")
                }
            )

            processed_count += 1
            if processed_count % COMMIT_BATCH_SIZE == 0:
                db.commit()

        # Finalize batch status and rates
        total_records = batch.total_records or 1
        match_rate_ai = round((ai_resolved_count / total_records * 100.0), 2)
        
        batch.status = BatchStatus.reasoning_complete
        batch.matched_ai_resolved_count = ai_resolved_count
        batch.match_rate_ai_resolved = match_rate_ai
        batch.unresolved_count = unresolved_count

        elapsed_ms = int((datetime.now(timezone.utc).replace(tzinfo=None) - start_time).total_seconds() * 1000)
        batch.duration_ms = elapsed_ms

        db.commit()

    except Exception as e:
        db.rollback()
        logger.exception(f"[reasoning_pipeline] Fatal error for batch {batch_id}: {e}")
        try:
            batch = db.query(Batch).filter(Batch.id == batch_id).first()
            if batch:
                batch.status = BatchStatus.failed
                db.commit()
        except Exception as inner:
            logger.exception(f"[reasoning_pipeline] Failed to mark batch {batch_id} as failed: {inner}")
    finally:
        db.close()
