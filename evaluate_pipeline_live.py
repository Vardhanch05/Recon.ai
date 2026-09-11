import asyncio
import json
import uuid
import sys
from backend.main import app
from fastapi.testclient import TestClient
from backend.reasoning import run_batch_reasoning_pipeline
from backend.database import SessionLocal

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

client = TestClient(app)

print("=" * 70)
print(" 1. HEALTH CHECK & DATABASE CONNECTIVITY")
print("=" * 70)
res_health = client.get("/health")
print(f"Status Code: {res_health.status_code}")
print(f"Payload: {json.dumps(res_health.json(), indent=2)}")

print("\n" + "=" * 70)
print(" 2. INGESTION: UPLOAD SETTLEMENT & LEDGER CSVs")
print("=" * 70)
with open("data/synthetic_batch.csv", "rb") as sf, open("data/ledger.csv", "rb") as lf:
    res_upload = client.post(
        "/batches/upload",
        files={
            "settlement_file": ("synthetic_batch.csv", sf.read(), "text/csv"),
            "ledger_file": ("ledger.csv", lf.read(), "text/csv")
        },
        data={"timestamp_tolerance_seconds": 2}
    )
upload_data = res_upload.json()
batch_id = upload_data["batch_id"]
print(f"Batch ID: {batch_id}")
print(f"Total Ingested Records: {upload_data['total_records']}")
print(f"Ingestion Errors: {upload_data['ingestion_error_count']}")
print(f"Batch Status: {upload_data['status']}")

print("\n" + "=" * 70)
print(" 3. DETERMINISTIC MATCHING ENGINE (PASS 1)")
print("=" * 70)
res_match = client.post(f"/batches/{batch_id}/run-matching")
match_data = res_match.json()
print(f"Deterministic Matched Count: {match_data['matched_deterministic_count']}")
print(f"Deterministic Match Rate: {match_data['match_rate_deterministic_pct']}%")
print(f"Exception Count: {match_data['exception_count']}")
print(f"Batch Status: {match_data['status']}")

print("\n" + "=" * 70)
print(" 4. AI DISCREPANCY REASONING PIPELINE (GROQ LLM)")
print("=" * 70)
asyncio.run(run_batch_reasoning_pipeline(uuid.UUID(batch_id), SessionLocal))
print("Async reasoning pipeline completed.")

print("\n" + "=" * 70)
print(" 5. BATCH SUMMARY & MATCH BREAKDOWN")
print("=" * 70)
res_sum = client.get(f"/batches/{batch_id}/summary")
sum_data = res_sum.json()
print(json.dumps(sum_data, indent=2))

print("\n" + "=" * 70)
print(" 6. EXCEPTION QUEUE & REASONING CARDS")
print("=" * 70)
res_exc = client.get(f"/batches/{batch_id}/exceptions?limit=50")
exc_data = res_exc.json()
print(f"Total Exceptions in Queue: {exc_data['total']}\n")

for idx, item in enumerate(exc_data["items"], start=1):
    s = item["settlement_record"]
    c = item["reasoning_card"]
    print(f"[{idx}] Gateway Txn: {s['gateway_txn_id']} | Order: {s['order_id']}")
    print(f"    Settled: ₹{s['settled_amount']:.2f} | Discrepancy: ₹{item['discrepancy_amount'] or 0.0:.2f}")
    print(f"    Status: {item['status']} | Routing: {item['routing_reason']}")
    if c:
        print(f"    Suggested Category: {c['suggested_category']} | Confidence: {c['confidence_score']:.2f}")
        print(f"    Hypothesis: {c['hypothesis_text']}")
        print(f"    Breakdown: {c['calculation_breakdown']}")
    print("-" * 60)

print("\n" + "=" * 70)
print(" 7. ACCURACY REPORT EVALUATION AGAINST GROUND TRUTH")
print("=" * 70)
res_acc = client.get(f"/batches/{batch_id}/accuracy-report?ground_truth_path=data/ground_truth.csv")
acc_data = res_acc.json()
print(json.dumps(acc_data, indent=2))

print("\n" + "=" * 70)
print(" 8. IMMUTABLE AUDIT LOG TRAIL")
print("=" * 70)
res_audit = client.get(f"/batches/{batch_id}/audit-log")
audit_data = res_audit.json()
print(f"Total Audit Events: {audit_data['total']}")
for e in audit_data["events"]:
    actor_tag = f"({e['actor']})" if e['actor'] else ""
    print(f"  • {e['timestamp'][:19]} | Event: {e['event_type']:<18} | Actor: {e['actor']:<15}")
