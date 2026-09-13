import json
import uuid
import os
import time
import logging
import asyncio
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Any, Tuple, List, Optional, Union
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

def to_decimal(val: Any) -> Decimal:
    """Safely converts any numeric / string value to a Decimal."""
    if val is None:
        return Decimal("0.00")
    if isinstance(val, Decimal):
        return val
    return Decimal(str(val))


def compute_confidence(residual_gap: Union[float, Decimal]) -> Tuple[float, str]:
    """
    Mathematical single source of truth for confidence scores.
    NEVER relies on self-reported LLM confidence to prevent hallucinated scores.
    
    Formula:
      • gap <= 0.05 (<= 5 paise):  Score 0.95 to 0.99 -> 'resolved'
      • gap <= 0.50 (<= 50 paise): Score 0.70 to 0.94 -> 'resolved' (minor FX/rounding)
      • gap <= 5.00:              Score 0.30 to 0.69 -> 'low_confidence'
      • gap > 5.00:               Score 0.00         -> 'unresolved'
    """
    gap = abs(float(residual_gap))
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
    gap = abs(float(card["calculation_breakdown"].get("residual_gap", 999.0)))
    computed_confidence, computed_status = compute_confidence(gap)
    
    # Overwrite card confidence with server-computed value
    card["confidence_score"] = computed_confidence
    if computed_status != "resolved" and card.get("suggested_category") != "UNRESOLVED":
        card["suggested_category"] = "UNRESOLVED"
        card["requires_human_review"] = True
    return card


# --- 2. DETERMINISTIC MATH TOOL (Zero Hallucination Decimal Arithmetic) ---

def calculate_difference(
    billed_amount: Union[float, Decimal, str],
    settled_amount: Union[float, Decimal, str],
    fee_pct: Union[float, Decimal, str] = 0.0,
    gst_on_fee_pct: Union[float, Decimal, str] = 0.0,
    flat_surcharge: Union[float, Decimal, str] = 0.0,
    refund_amount: Union[float, Decimal, str] = 0.0,
    fx_adjustment: Union[float, Decimal, str] = 0.0
) -> Dict[str, Any]:
    """
    Isolated deterministic arithmetic calculation tool using Decimal arithmetic.
    LLMs are prohibited from doing mental math; they must call this tool.

    Formula (Decimal precision):
      fee = billed * (fee_pct / 100)
      gst = fee * (gst_on_fee_pct / 100)
      expected_settlement = billed - fee - gst - flat_surcharge - refund + fx_adjustment
      residual_gap = settled_amount - expected_settlement
    """
    billed_d = to_decimal(billed_amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    settled_d = to_decimal(settled_amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    fee_pct_d = to_decimal(fee_pct)
    gst_pct_d = to_decimal(gst_on_fee_pct)
    surcharge_d = to_decimal(flat_surcharge).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    refund_d = to_decimal(refund_amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    fx_d = to_decimal(fx_adjustment).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    fee = (billed_d * (fee_pct_d / Decimal("100.0"))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    gst_on_fee = (fee * (gst_pct_d / Decimal("100.0"))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    expected_settlement = (billed_d - fee - gst_on_fee - surcharge_d - refund_d + fx_d).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    residual_gap = (settled_d - expected_settlement).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return {
        "billed_amount": float(billed_d),
        "fee_pct_tested": float(fee_pct_d),
        "gst_on_fee_pct_tested": float(gst_pct_d),
        "flat_surcharge_tested": float(surcharge_d),
        "refund_amount_tested": float(refund_d),
        "fx_adjustment_tested": float(fx_d),
        "expected_settlement": float(expected_settlement),
        "actual_settlement": float(settled_d),
        "residual_gap": float(residual_gap)
    }


# --- 3. MULTI-HYPOTHESIS SEQUENTIAL EVALUATION GRAPH ---

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
    Evaluates discrepancy hypotheses sequentially through a deterministic state graph:
      Step 1: Domestic 2% MDR (+ optional 18% GST)
      Step 2: International 3% MDR (+ optional 18% GST)
      Step 3: MDR + Flat Gateway Surcharges (₹10, ₹15)
      Step 4: Partial Refund deductions (+ optional MDR)
      Step 5: Combined causes (MDR + GST + Surcharge + Refund)
      Step 6: Minor FX Rounding (<= ₹0.50)
      Step 7: UNRESOLVED Fallback
    """
    attempts = []
    
    # Step 1: Domestic standard MDR (2%) + Optional GST (18%)
    for gst in [0.0, 18.0]:
        calc = calculate_difference(billed_amount, settled_amount, fee_pct=2.0, gst_on_fee_pct=gst)
        step_name = f"domestic_2pct_mdr" + (f"_gst18" if gst > 0 else "")
        attempts.append(f"{step_name} (gap: ₹{calc['residual_gap']:.2f})")
        if abs(calc["residual_gap"]) <= 0.05:
            calc["attempts_tried"] = attempts
            return {
                "hypothesis_text": f"Shortfall matches 2% domestic MDR fee" + (f" with 18% GST (₹{calc['billed_amount'] * 0.02 * 0.18:.2f})." if gst > 0 else "."),
                "calculation_breakdown": calc,
                "confidence_score": 0.99,
                "suggested_category": DiscrepancyCategory.MDR_VARIANCE.value,
                "requires_human_review": False
            }

    # Step 2: International standard MDR (3%) + Optional GST (18%)
    for gst in [0.0, 18.0]:
        calc = calculate_difference(billed_amount, settled_amount, fee_pct=3.0, gst_on_fee_pct=gst)
        step_name = f"intl_3pct_mdr" + (f"_gst18" if gst > 0 else "")
        attempts.append(f"{step_name} (gap: ₹{calc['residual_gap']:.2f})")
        if abs(calc["residual_gap"]) <= 0.05:
            calc["attempts_tried"] = attempts
            return {
                "hypothesis_text": f"Shortfall matches 3% international card MDR fee" + (f" with 18% GST." if gst > 0 else "."),
                "calculation_breakdown": calc,
                "confidence_score": 0.99,
                "suggested_category": DiscrepancyCategory.MDR_VARIANCE.value,
                "requires_human_review": False
            }

    # Step 3: MDR + Flat Surcharges (₹10 / ₹15)
    for fee in [2.0, 3.0]:
        for surcharge in [10.0, 15.0]:
            calc = calculate_difference(billed_amount, settled_amount, fee_pct=fee, flat_surcharge=surcharge)
            attempts.append(f"mdr_{int(fee)}pct_surcharge_{int(surcharge)} (gap: ₹{calc['residual_gap']:.2f})")
            if abs(calc["residual_gap"]) <= 0.05:
                calc["attempts_tried"] = attempts
                return {
                    "hypothesis_text": f"Shortfall matches {int(fee)}% MDR fee plus a flat ₹{int(surcharge)} gateway processing surcharge.",
                    "calculation_breakdown": calc,
                    "confidence_score": 0.99,
                    "suggested_category": DiscrepancyCategory.MDR_VARIANCE.value,
                    "requires_human_review": False
                }

    # Step 4: Partial Refund Deduction
    if known_refund and known_refund > 0:
        for fee in [0.0, 2.0, 3.0]:
            for gst in [0.0, 18.0]:
                calc = calculate_difference(billed_amount, settled_amount, fee_pct=fee, gst_on_fee_pct=gst, refund_amount=known_refund)
                attempts.append(f"refund_{int(known_refund)}_fee_{fee} (gap: ₹{calc['residual_gap']:.2f})")
                if abs(calc["residual_gap"]) <= 0.05:
                    calc["attempts_tried"] = attempts
                    return {
                        "hypothesis_text": f"Shortfall matches a customer partial refund of ₹{known_refund:.2f}" + (f" combined with {fee}% MDR and GST." if fee > 0 else "."),
                        "calculation_breakdown": calc,
                        "confidence_score": 0.99,
                        "suggested_category": DiscrepancyCategory.PARTIAL_REFUND.value,
                        "requires_human_review": False
                    }

    # Step 5: Combined Cause: 3% Intl MDR + 18% GST + Flat Surcharge (+ Optional Known Refund)
    for surcharge in [10.0, 15.0]:
        refund_val = known_refund if (known_refund and known_refund > 0) else 0.0
        calc = calculate_difference(billed_amount, settled_amount, fee_pct=3.0, gst_on_fee_pct=18.0, flat_surcharge=surcharge, refund_amount=refund_val)
        attempts.append(f"combined_intl3_gst18_sur{int(surcharge)}_ref{int(refund_val)} (gap: ₹{calc['residual_gap']:.2f})")
        if abs(calc["residual_gap"]) <= 0.05:
            text = f"Shortfall matches combined 3% international MDR with 18% GST and flat ₹{int(surcharge)} surcharge"
            if refund_val > 0:
                text += f", and ₹{refund_val:.2f} partial refund."
            else:
                text += "."
            calc["attempts_tried"] = attempts
            return {
                "hypothesis_text": text,
                "calculation_breakdown": calc,
                "confidence_score": 0.99,
                "suggested_category": DiscrepancyCategory.MDR_VARIANCE.value,
                "requires_human_review": False
            }

    # Step 6: Minor FX Rounding variance (<= ₹0.50)
    for fee in [2.0, 3.0]:
        for gst in [0.0, 18.0]:
            calc = calculate_difference(billed_amount, settled_amount, fee_pct=fee, gst_on_fee_pct=gst)
            if abs(calc["residual_gap"]) <= 0.50:
                calc["fx_adjustment_tested"] = round(calc["residual_gap"], 2)
                calc["attempts_tried"] = attempts
                return {
                    "hypothesis_text": f"Shortfall matches {int(fee)}% MDR conversion with a minor FX rounding variance of ₹{abs(calc['residual_gap']):.2f}.",
                    "calculation_breakdown": calc,
                    "confidence_score": 0.92,
                    "suggested_category": DiscrepancyCategory.FX_ROUNDING.value,
                    "requires_human_review": False
                }

    # Step 7: Unresolved anomaly
    raw_gap = round(billed_amount - settled_amount, 2)
    return {
        "hypothesis_text": f"No combination of known fee, tax, surcharge, or refund schedules explains a ₹{raw_gap:.2f} gap. Flagged for manual investigation.",
        "calculation_breakdown": {
            "billed_amount": billed_amount,
            "actual_settlement": settled_amount,
            "residual_gap": raw_gap,
            "attempts_tried": attempts
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
    Builds context, invokes sequential hypothesis graph / LLM testing,
    applies server-side validate_card override, and returns (validated_card, actor).
    """
    if not candidate_order:
        unresolved_card = {
            "hypothesis_text": "No candidate order ledger entry found to reconcile against.",
            "calculation_breakdown": {
                "billed_amount": None,
                "actual_settlement": settlement_data["settled_amount"],
                "residual_gap": settlement_data["settled_amount"],
                "attempts_tried": ["no_candidate_order_found"]
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

    # Fallback to sequential multi-hypothesis evaluation graph
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
    Commits per processed exception to release the global audit lock periodically.
    """
    db = db_session_factory()
    t0 = time.perf_counter()
    try:
        batch = db.query(Batch).filter(Batch.id == batch_id).first()
        if not batch:
            logger.error(f"Batch {batch_id} not found in reasoning pipeline.")
            return

        exceptions = db.query(ReconciliationResult).filter(
            ReconciliationResult.batch_id == batch_id,
            ReconciliationResult.status == ReconciliationStatus.exception_unresolved
        ).all()

        if not exceptions:
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            batch.duration_ms = (batch.duration_ms or 0) + elapsed_ms
            batch.status = BatchStatus.reasoning_complete
            db.commit()
            return

        tasks = []
        for exc in exceptions:
            settle_row = db.query(SettlementRecord).filter(
                SettlementRecord.id == exc.settlement_record_id
            ).first()

            cand_order = None
            if exc.order_ledger_id:
                cand_order_row = db.query(OrderLedger).filter(
                    OrderLedger.id == exc.order_ledger_id
                ).first()
                if cand_order_row:
                    cand_order = {
                        "billed_amount": float(cand_order_row.billed_amount),
                        "is_international": cand_order_row.is_international,
                        "refund_amount": float(cand_order_row.refund_amount) if cand_order_row.refund_amount else 0.0
                    }

            settle_data = {
                "settled_amount": float(settle_row.settled_amount),
                "gateway_txn_id": settle_row.gateway_txn_id
            }

            tasks.append((exc, settle_data, cand_order))

        # Process exceptions sequentially with chunked commits (every 10 records) to balance locking and I/O
        resolved_count = 0
        unresolved_count = 0
        CHUNK_SIZE = 10

        for idx, (exc, s_data, c_order) in enumerate(tasks, start=1):
            card_dict, actor = await process_single_exception(exc.id, s_data, c_order, db)

            # Map category enum
            cat_str = card_dict["suggested_category"]
            try:
                cat_enum = DiscrepancyCategory[cat_str]
            except KeyError:
                cat_enum = DiscrepancyCategory.UNRESOLVED

            # Upsert ReasoningCard
            reasoning_card = db.query(ReasoningCard).filter(
                ReasoningCard.reconciliation_result_id == exc.id
            ).first()

            breakdown_json = json.dumps(card_dict["calculation_breakdown"])

            if not reasoning_card:
                reasoning_card = ReasoningCard(
                    id=uuid.uuid4(),
                    reconciliation_result_id=exc.id,
                    hypothesis_text=card_dict["hypothesis_text"],
                    calculation_breakdown=breakdown_json,
                    confidence_score=card_dict["confidence_score"],
                    suggested_category=cat_enum,
                    requires_human_review=card_dict["requires_human_review"]
                )
                db.add(reasoning_card)
            else:
                reasoning_card.hypothesis_text = card_dict["hypothesis_text"]
                reasoning_card.calculation_breakdown = breakdown_json
                reasoning_card.confidence_score = card_dict["confidence_score"]
                reasoning_card.suggested_category = cat_enum
                reasoning_card.requires_human_review = card_dict["requires_human_review"]

            # Update reconciliation result status
            if cat_enum != DiscrepancyCategory.UNRESOLVED and card_dict["confidence_score"] >= 0.70:
                exc.status = ReconciliationStatus.matched_ai_resolved
                exc.resolution_source = ResolutionSource.llm_reasoner
                exc.confidence_score = card_dict["confidence_score"]
                resolved_count += 1
            else:
                exc.status = ReconciliationStatus.exception_unresolved
                unresolved_count += 1

            # Log audit event
            log_audit_event(
                db=db,
                batch_id=batch_id,
                event_type=AuditEventType.llm_call,
                actor=actor,
                payload={
                    "reconciliation_result_id": str(exc.id),
                    "suggested_category": cat_enum.value,
                    "confidence_score": card_dict["confidence_score"],
                    "residual_gap": card_dict["calculation_breakdown"].get("residual_gap", 0.0)
                }
            )

            # Heartbeat update and commit periodically every CHUNK_SIZE records
            if idx % CHUNK_SIZE == 0 or idx == len(tasks):
                batch.reasoning_started_at = datetime.now(timezone.utc).replace(tzinfo=None)
                db.commit()

        # Update batch summary
        batch.matched_ai_resolved_count = resolved_count
        batch.unresolved_count = unresolved_count
        if batch.total_records and batch.total_records > 0:
            batch.match_rate_ai_resolved = round((resolved_count / batch.total_records) * 100.0, 2)

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        batch.duration_ms = (batch.duration_ms or 0) + elapsed_ms
        batch.status = BatchStatus.reasoning_complete
        db.commit()
        logger.info(f"Reasoning completed for batch {batch_id} in {elapsed_ms}ms: {resolved_count} resolved, {unresolved_count} unresolved.")

    except Exception as e:
        logger.error(f"Error in batch reasoning pipeline for {batch_id}: {e}", exc_info=True)
        db.rollback()
        batch = db.query(Batch).filter(Batch.id == batch_id).first()
        if batch:
            batch.status = BatchStatus.failed
            db.commit()
    finally:
        db.close()
