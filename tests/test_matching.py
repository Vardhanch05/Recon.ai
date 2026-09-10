import io
import pytest
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)

# Dataset with 5 transactions:
# 1. pay_001 -> ord_100: exact order_id match (₹950 + ₹50 fee = ₹1000) -> matched_deterministic (order_id_match)
# 2. pay_002 -> ord_101: order_id match with no fee in settlement (₹2000 billed) -> matched_deterministic
# 3. pay_003 -> ord_102: no order_id in settlement, but ₹475 + ₹25 fee = ₹500 within timestamp -> matched_deterministic (amount_match)
# 4. pay_004 -> ord_103: order_id match, but ₹900 billed, fee ₹50, settled ₹800 (gap ₹50) -> amount_mismatch exception
# 5. pay_005 -> ord_unknown: no match -> no_match exception

SAMPLE_SETTLEMENT = """gateway_txn_id,order_id,settled_amount,settlement_timestamp,fee_deducted,currency
pay_001,ord_100,950.00,2026-09-01T10:00:00Z,50.00,INR
pay_002,ord_101,2000.00,2026-09-01T10:05:00Z,,INR
pay_003,,475.00,2026-09-01T10:10:00Z,25.00,INR
pay_004,ord_103,800.00,2026-09-01T10:15:00Z,50.00,INR
pay_005,ord_999,999.00,2026-09-01T10:20:00Z,,INR
"""

SAMPLE_LEDGER = """order_id,billed_amount,order_timestamp,refund_amount,is_international,payment_method
ord_100,1000.00,2026-09-01T10:00:00Z,0.00,false,card
ord_101,2000.00,2026-09-01T10:05:00Z,0.00,false,upi
ord_102,500.00,2026-09-01T10:10:00Z,0.00,false,netbanking
ord_103,900.00,2026-09-01T10:15:00Z,0.00,false,card
"""

def test_deterministic_matching_and_approval_guards():
    # 1. Upload Batch
    upload_res = client.post(
        "/batches/upload",
        files={
            "settlement_file": ("settlement.csv", io.BytesIO(SAMPLE_SETTLEMENT.encode("utf-8")), "text/csv"),
            "ledger_file": ("ledger.csv", io.BytesIO(SAMPLE_LEDGER.encode("utf-8")), "text/csv"),
        },
        data={"timestamp_tolerance_seconds": 2}
    )
    assert upload_res.status_code == 200
    batch_id = upload_res.json()["batch_id"]

    # 2. Run Deterministic Matching
    match_res = client.post(f"/batches/{batch_id}/run-matching")
    assert match_res.status_code == 200
    match_data = match_res.json()
    assert match_data["matched_deterministic_count"] == 3  # pay_001, pay_002, pay_003
    assert match_data["exception_count"] == 2             # pay_004 (mismatch), pay_005 (no match)
    assert match_data["match_rate_deterministic_pct"] == 60.0

    # 3. Query Exceptions List
    exc_res = client.get(f"/batches/{batch_id}/exceptions")
    assert exc_res.status_code == 200
    exc_data = exc_res.json()
    assert exc_data["total"] == 2
    
    # 4. Try approving an unresolved exception (Should fail with 400 Bad Request)
    unresolved_result_id = exc_data["items"][0]["reconciliation_result_id"]
    approve_fail = client.post(f"/reconciliation/{unresolved_result_id}/approve")
    assert approve_fail.status_code == 400
    assert "Unresolved exceptions cannot be approved" in approve_fail.json()["detail"]

    # 5. Reject the unresolved exception (Should succeed with 200 OK)
    reject_res = client.post(
        f"/reconciliation/{unresolved_result_id}/reject",
        json={"reviewed_by": "lead_accountant", "override_note": "Route to manual review"}
    )
    assert reject_res.status_code == 200
    assert reject_res.json()["status"] == "human_rejected"

    # 6. Double-reject / Double-action (Should return 409 Conflict)
    double_reject = client.post(
        f"/reconciliation/{unresolved_result_id}/reject",
        json={"reviewed_by": "lead_accountant"}
    )
    assert double_reject.status_code == 409

    # 7. Test invalid audit event_type filter returns 422 Unprocessable Entity
    invalid_audit_res = client.get(f"/batches/{batch_id}/audit-log?event_type=non_existent_event_type")
    assert invalid_audit_res.status_code == 422
    assert "Invalid event_type" in invalid_audit_res.json()["detail"]

