import os
import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.reasoning import run_batch_reasoning_pipeline
from tests.conftest import TestingSessionLocal
import uuid

client = TestClient(app)

@pytest.mark.asyncio
async def test_full_reconciliation_pipeline():
    # 1. Read synthetic datasets
    with open("data/synthetic_batch.csv", "rb") as f:
        settle_bytes = f.read()
    with open("data/ledger.csv", "rb") as f:
        ledger_bytes = f.read()

    # 2. Upload Batch
    upload_res = client.post(
        "/batches/upload",
        files={
            "settlement_file": ("synthetic_batch.csv", settle_bytes, "text/csv"),
            "ledger_file": ("ledger.csv", ledger_bytes, "text/csv"),
        },
        data={"timestamp_tolerance_seconds": 2}
    )
    assert upload_res.status_code == 200
    batch_id = upload_res.json()["batch_id"]

    # 3. Trigger Deterministic Matching (80% match rate expectation)
    match_res = client.post(f"/batches/{batch_id}/run-matching")
    assert match_res.status_code == 200
    match_data = match_res.json()
    assert match_data["matched_deterministic_count"] == 44
    assert match_data["exception_count"] == 11
    assert match_data["match_rate_deterministic_pct"] == 80.0

    # 4. Run Reasoning Pipeline synchronously in test
    await run_batch_reasoning_pipeline(uuid.UUID(batch_id), TestingSessionLocal)

    # 5. Check Summary after Reasoning Complete
    summary_res = client.get(f"/batches/{batch_id}/summary")
    assert summary_res.status_code == 200
    summary_data = summary_res.json()
    assert summary_data["status"] == "reasoning_complete"
    assert summary_data["matched_deterministic_count"] == 44
    assert summary_data["matched_ai_resolved_count"] == 8
    assert summary_data["unresolved_count"] == 3

    # 6. Verify Accuracy Report against Ground Truth Key
    acc_res = client.get(f"/batches/{batch_id}/accuracy-report?ground_truth_path=data/ground_truth.csv")
    assert acc_res.status_code == 200
    acc_data = acc_res.json()
    assert acc_data["total_evaluated"] == 11
    assert acc_data["explainable_total"] == 8
    assert acc_data["explainable_correct"] == 8
    assert acc_data["explainable_accuracy_pct"] == 100.0
    assert acc_data["unresolvable_total"] == 3
    assert acc_data["unresolvable_correct"] == 3
    assert acc_data["unresolvable_accuracy_pct"] == 100.0
    assert acc_data["overall_accuracy_pct"] == 100.0

    # 7. Query Exceptions List and verify cards structure
    exc_res = client.get(f"/batches/{batch_id}/exceptions")
    assert exc_res.status_code == 200
    exc_data = exc_res.json()
    assert exc_data["total"] == 11
    
    resolved_cards = [i for i in exc_data["items"] if i["status"] == "matched_ai_resolved"]
    unresolved_cards = [i for i in exc_data["items"] if i["status"] == "exception_unresolved"]

    assert len(resolved_cards) == 8
    assert len(unresolved_cards) == 3

    for r in resolved_cards:
        assert r["reasoning_card"] is not None
        assert "calculation_breakdown" in r["reasoning_card"]
        assert r["reasoning_card"]["confidence_score"] >= 0.70
        assert r["reasoning_card"]["suggested_category"] in ["MDR_VARIANCE", "PARTIAL_REFUND", "FX_ROUNDING"]

    for u in unresolved_cards:
        assert u["reasoning_card"] is not None
        assert u["reasoning_card"]["confidence_score"] == 0.0
        assert u["reasoning_card"]["suggested_category"] == "UNRESOLVED"

    # 8. Approve an AI-resolved item
    resolved_item = resolved_cards[0]
    approve_res = client.post(
        f"/reconciliation/{resolved_item['reconciliation_result_id']}/approve",
        json={"reviewed_by": "lead_controller"}
    )
    assert approve_res.status_code == 200
    assert approve_res.json()["status"] == "human_approved"
    assert approve_res.json()["journal_posted"] is True

    # 9. Verify Audit Trail has logged ingestion, matches, LLM calls, and approval
    audit_res = client.get(f"/batches/{batch_id}/audit-log")
    assert audit_res.status_code == 200
    audit_data = audit_res.json()
    event_types = [e["event_type"] for e in audit_data["events"]]
    assert "match" in event_types
    assert "llm_call" in event_types
    assert "human_approval" in event_types
    assert "journal_posted" in event_types
