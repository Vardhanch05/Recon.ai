import csv
import os
import json
import pathlib
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload
import uuid

from backend.database import get_db
from backend.models import Batch, ReconciliationResult, ReasoningCard, ReconciliationStatus
from backend.schemas import AccuracyReportResponse

router = APIRouter(tags=["Reports"])

@router.get("/batches/{batch_id}/accuracy-report", response_model=AccuracyReportResponse)
def get_accuracy_report(
    batch_id: uuid.UUID,
    ground_truth_path: Optional[str] = Query("data/ground_truth.csv"),
    db: Session = Depends(get_db)
):
    """
    Evaluates AI reasoner outputs against the ground truth answer key.
    Returns confusion matrix and accuracy breakdown for explainable and unresolvable records.
    """
    batch = db.query(Batch).filter(Batch.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Batch not found")

    # FIX C5: Validate path is within the safe data/ directory to prevent path traversal
    try:
        safe_dir = pathlib.Path("data").resolve()
        requested_path = pathlib.Path(ground_truth_path).resolve()
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid file path.")

    if not str(requested_path).startswith(str(safe_dir)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access to this path is not permitted. Files must reside in the data/ directory."
        )

    if not requested_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ground truth file not found at {ground_truth_path}"
        )

    # Load Ground Truth mapping by gateway_txn_id
    truth_map = {}
    with open(requested_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            truth_map[row["gateway_txn_id"]] = {
                "true_category": row["true_category"].strip(),
                "true_cause": row.get("true_cause", ""),
                "expected_residual_gap": float(row.get("expected_residual_gap", 0.0))
            }

    # Fetch all cards for this batch with eager loading to prevent N+1 queries
    results = db.query(ReconciliationResult).filter(
        ReconciliationResult.batch_id == batch_id
    ).options(
        joinedload(ReconciliationResult.settlement_record),
        joinedload(ReconciliationResult.reasoning_card)
    ).all()

    explainable_total = 0
    explainable_correct = 0
    unresolvable_total = 0
    unresolvable_correct = 0

    confusion_matrix = {
        "true_positives_explainable": 0,
        "true_negatives_unresolvable": 0,
        "false_positives": 0,
        "false_negatives": 0,
        "category_breakdown": {}
    }

    evaluated_count = 0

    for r in results:
        txn_id = r.settlement_record.gateway_txn_id
        if txn_id not in truth_map:
            continue

        evaluated_count += 1
        truth = truth_map[txn_id]
        true_cat = truth["true_category"]

        # Card output
        pred_cat = "UNRESOLVED"
        if r.reasoning_card:
            pred_cat = r.reasoning_card.suggested_category

        confusion_matrix["category_breakdown"].setdefault(true_cat, {"total": 0, "correct": 0})
        confusion_matrix["category_breakdown"][true_cat]["total"] += 1

        if true_cat == "UNRESOLVED":
            unresolvable_total += 1
            if pred_cat == "UNRESOLVED":
                unresolvable_correct += 1
                confusion_matrix["true_negatives_unresolvable"] += 1
                confusion_matrix["category_breakdown"][true_cat]["correct"] += 1
            else:
                confusion_matrix["false_positives"] += 1
        else:
            explainable_total += 1
            # FIX A4: Strict evaluation — predicted category must match ground truth category exactly
            if pred_cat == true_cat:
                explainable_correct += 1
                confusion_matrix["true_positives_explainable"] += 1
                confusion_matrix["category_breakdown"][true_cat]["correct"] += 1
            else:
                confusion_matrix["false_negatives"] += 1

    exp_acc = round((explainable_correct / explainable_total * 100.0), 2) if explainable_total > 0 else 100.0
    unres_acc = round((unresolvable_correct / unresolvable_total * 100.0), 2) if unresolvable_total > 0 else 100.0
    total_correct = explainable_correct + unresolvable_correct
    overall_acc = round((total_correct / evaluated_count * 100.0), 2) if evaluated_count > 0 else 100.0

    return AccuracyReportResponse(
        total_evaluated=evaluated_count,
        explainable_total=explainable_total,
        explainable_correct=explainable_correct,
        explainable_accuracy_pct=exp_acc,
        unresolvable_total=unresolvable_total,
        unresolvable_correct=unresolvable_correct,
        unresolvable_accuracy_pct=unres_acc,
        overall_accuracy_pct=overall_acc,
        confusion_matrix=confusion_matrix
    )
