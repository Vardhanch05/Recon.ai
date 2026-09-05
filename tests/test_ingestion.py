import io
import pytest
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)

SAMPLE_SETTLEMENT_CSV = """gateway_txn_id,order_id,settled_amount,settlement_timestamp,fee_deducted,currency
pay_001,ord_100,950.00,2026-09-01T10:00:00Z,50.00,INR
pay_002,ord_101,1900.00,2026-09-01T10:05:00Z,100.00,INR
pay_003,,475.00,2026-09-01T10:10:00Z,25.00,INR
invalid_row_no_amount,,NOT_A_NUMBER,2026-09-01T10:15:00Z,,INR
"""

SAMPLE_LEDGER_CSV = """order_id,billed_amount,order_timestamp,refund_amount,is_international,payment_method
ord_100,1000.00,2026-09-01T10:00:00Z,0.00,false,card
ord_101,2000.00,2026-09-01T10:05:00Z,0.00,false,upi
ord_102,500.00,2026-09-01T10:10:00Z,0.00,false,netbanking
"""

def test_upload_and_summary():
    # 1. Upload both CSV files
    response = client.post(
        "/batches/upload",
        files={
            "settlement_file": ("settlement.csv", io.BytesIO(SAMPLE_SETTLEMENT_CSV.encode("utf-8")), "text/csv"),
            "ledger_file": ("ledger.csv", io.BytesIO(SAMPLE_LEDGER_CSV.encode("utf-8")), "text/csv"),
        },
        data={"timestamp_tolerance_seconds": 2}
    )

    assert response.status_code == 200
    data = response.json()
    assert "batch_id" in data
    assert data["status"] == "uploaded"
    assert data["total_records"] == 3  # 3 valid settlement records
    assert data["ingestion_error_count"] == 1  # 1 malformed row

    batch_id = data["batch_id"]

    # 2. Check Batch Summary
    summary_resp = client.get(f"/batches/{batch_id}/summary")
    assert summary_resp.status_code == 200
    summary_data = summary_resp.json()
    assert summary_data["batch_id"] == batch_id
    assert summary_data["status"] == "uploaded"
    assert summary_data["total_records"] == 3
    assert summary_data["ingestion_error_count"] == 1

    # 3. Check Audit Log (should record ingestion_error)
    audit_resp = client.get(f"/batches/{batch_id}/audit-log")
    assert audit_resp.status_code == 200
    audit_data = audit_resp.json()
    assert audit_data["total"] >= 1
    assert audit_data["events"][0]["event_type"] == "ingestion_error"
