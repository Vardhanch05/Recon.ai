import asyncio
import json
import uuid
import sys
import time
from backend.main import app
from fastapi.testclient import TestClient
from backend.reasoning import run_batch_reasoning_pipeline
from backend.database import SessionLocal

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

client = TestClient(app)

print("=" * 75)
print(" 🚀 RECON.AI LARGE DATASET BENCHMARK EVALUATION (1,000 RECORDS)")
print("=" * 75)

# 1. Health check
res_health = client.get("/health")
assert res_health.status_code == 200, "Health check failed"

# 2. Ingestion
t0 = time.perf_counter()
with open("data/synthetic_batch_large.csv", "rb") as sf, open("data/ledger_large.csv", "rb") as lf:
    res_upload = client.post(
        "/batches/upload",
        files={
            "settlement_file": ("synthetic_batch_large.csv", sf.read(), "text/csv"),
            "ledger_file": ("ledger_large.csv", lf.read(), "text/csv")
        },
        data={"timestamp_tolerance_seconds": 2}
    )
t_ingest = (time.perf_counter() - t0) * 1000

upload_data = res_upload.json()
batch_id = upload_data["batch_id"]
total_records = upload_data["total_records"]
ingestion_errors = upload_data["ingestion_error_count"]

print(f"\n[1/5] INGESTION COMPLETED in {t_ingest:.2f} ms")
print(f"      Batch ID: {batch_id}")
print(f"      Total Ingested Records: {total_records}")
print(f"      Ingestion Errors: {ingestion_errors}")

# 3. Deterministic Matching
t0 = time.perf_counter()
res_match = client.post(f"/batches/{batch_id}/run-matching")
t_match = (time.perf_counter() - t0) * 1000

match_data = res_match.json()
matched_det = match_data["matched_deterministic_count"]
det_pct = match_data["match_rate_deterministic_pct"]
exception_count = match_data["exception_count"]

print(f"\n[2/5] DETERMINISTIC MATCHING COMPLETED in {t_match:.2f} ms")
print(f"      Deterministic Matches: {matched_det} ({det_pct:.1f}%)")
print(f"      Exceptions Routed to Reasoner: {exception_count} ({(exception_count/total_records)*100:.1f}%)")

# 4. Asynchronous AI Discrepancy Reasoning
t0 = time.perf_counter()
asyncio.run(run_batch_reasoning_pipeline(uuid.UUID(batch_id), SessionLocal))
t_reason = (time.perf_counter() - t0) * 1000

print(f"\n[3/5] AI DISCREPANCY REASONING COMPLETED in {t_reason:.2f} ms ({t_reason/1000:.2f}s)")
print(f"      Exceptions Processed: {exception_count}")
print(f"      Avg Latency per Exception: {t_reason/exception_count:.2f} ms")

# 5. Batch Summary
res_sum = client.get(f"/batches/{batch_id}/summary")
sum_data = res_sum.json()
ai_resolved = sum_data["matched_ai_resolved_count"]
ai_pct = sum_data["match_rate_ai_resolved_pct"]
unresolved = sum_data["unresolved_count"]
unres_pct = (unresolved / total_records) * 100

print(f"\n[4/5] PIPELINE SUMMARY & BREAKDOWN")
print(f"      Status: {sum_data['status']}")
print(f"      Deterministic Matches: {matched_det} ({det_pct:.2f}%)")
print(f"      AI Resolved Matches:   {ai_resolved} ({ai_pct:.2f}%)")
print(f"      Unresolved Anomalies:  {unresolved} ({unres_pct:.2f}%)")
print(f"      Total Coverage:        {matched_det + ai_resolved} ({((matched_det + ai_resolved)/total_records)*100:.2f}%)")

# 6. Accuracy Report against Ground Truth
res_acc = client.get(f"/batches/{batch_id}/accuracy-report?ground_truth_path=data/ground_truth_large.csv")
acc_data = res_acc.json()

print(f"\n[5/5] GROUND TRUTH ACCURACY REPORT (1,000 RECORDS BENCHMARK)")
print(f"      Total Evaluated Non-Trivial Records: {acc_data['total_evaluated']}")
print(f"      Explainable Records Accuracy:        {acc_data['explainable_correct']} / {acc_data['explainable_total']} ({acc_data['explainable_accuracy_pct']}%)")
print(f"      Unresolvable Detection Specificity:  {acc_data['unresolvable_correct']} / {acc_data['unresolvable_total']} ({acc_data['unresolvable_accuracy_pct']}%)")
print(f"      Overall Accuracy:                    {acc_data['overall_accuracy_pct']}%")

cm = acc_data["confusion_matrix"]
print(f"\n      CONFUSION MATRIX:")
print(f"      • True Positives (Explainable): {cm['true_positives_explainable']}")
print(f"      • True Negatives (Unresolvable): {cm['true_negatives_unresolvable']}")
print(f"      • False Positives:               {cm['false_positives']}")
print(f"      • False Negatives:               {cm['false_negatives']}")
print(f"\n      CATEGORY PRECISION BREAKDOWN:")
for cat, stats in cm["category_breakdown"].items():
    prec = (stats["correct"] / stats["total"]) * 100 if stats["total"] > 0 else 100
    print(f"      - {cat:<22}: {stats['correct']:>3} / {stats['total']:>3} ({prec:.1f}%)")

# 7. Audit Log Count
res_audit = client.get(f"/batches/{batch_id}/audit-log")
audit_data = res_audit.json()
print(f"\n      Audit Trail Events Logged: {audit_data['total']}")

# Return dict of metrics for metrics.txt
metrics_result = {
    "total_records": total_records,
    "ingestion_latency_ms": round(t_ingest, 2),
    "matching_latency_ms": round(t_match, 2),
    "reasoning_latency_ms": round(t_reason, 2),
    "avg_reasoning_per_rec_ms": round(t_reason / exception_count, 2),
    "matched_deterministic_count": matched_det,
    "match_rate_deterministic_pct": det_pct,
    "matched_ai_resolved_count": ai_resolved,
    "match_rate_ai_resolved_pct": ai_pct,
    "unresolved_count": unresolved,
    "unresolved_pct": round(unres_pct, 2),
    "total_coverage_pct": round(((matched_det + ai_resolved) / total_records) * 100, 2),
    "explainable_accuracy_pct": acc_data["explainable_accuracy_pct"],
    "unresolvable_accuracy_pct": acc_data["unresolvable_accuracy_pct"],
    "overall_accuracy_pct": acc_data["overall_accuracy_pct"],
    "confusion_matrix": cm,
    "audit_events_count": audit_data["total"]
}

with open("metrics_raw.json", "w") as f:
    json.dump(metrics_result, f, indent=2)

print("\n" + "=" * 75)
print(" Benchmark finished successfully! Raw metrics saved to metrics_raw.json")
print("=" * 75)
