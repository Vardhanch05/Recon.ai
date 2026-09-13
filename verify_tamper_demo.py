import uuid
import json
from sqlalchemy import text
from backend.database import SessionLocal, Base, engine
import backend.models as models
from backend.audit import log_audit_event, verify_audit_chain, AuditEventType

Base.metadata.create_all(bind=engine)
db = SessionLocal()
batch_id = uuid.uuid4()

print("=" * 65)
print(" 1. LOGGING 4 CHAINED AUDIT EVENTS")
print("=" * 65)
e1 = log_audit_event(db, batch_id, AuditEventType.ingestion_error, "system", {"error": "none"})
e2 = log_audit_event(db, batch_id, AuditEventType.match, "rule_engine", {"matched": 800})
e3 = log_audit_event(db, batch_id, AuditEventType.llm_call, "rule_reasoner", {"cat": "MDR_VARIANCE"})
e4 = log_audit_event(db, batch_id, AuditEventType.human_approval, "controller_01", {"action": "approved"})
db.commit()

print(f"Event 1 | Seq: {e1.sequence_num} | Hash: {e1.current_hash[:16]}... | Prev: {e1.prev_hash[:16]}...")
print(f"Event 2 | Seq: {e2.sequence_num} | Hash: {e2.current_hash[:16]}... | Prev: {e2.prev_hash[:16]}...")
print(f"Event 3 | Seq: {e3.sequence_num} | Hash: {e3.current_hash[:16]}... | Prev: {e3.prev_hash[:16]}...")
print(f"Event 4 | Seq: {e4.sequence_num} | Hash: {e4.current_hash[:16]}... | Prev: {e4.prev_hash[:16]}...")

# 2. Verify clean chain
res_clean = verify_audit_chain(db)
print("\n--- CLEAN CHAIN VERIFICATION ---")
print(f"Is Valid: {res_clean['is_valid']}")
print(f"Total Verified: {res_clean['total_verified_events']}")
print(f"Message: {res_clean['message']}")

# 3. Simulate raw SQL tampering on event #2
print("\n--- SIMULATING RAW SQL TAMPERING ON EVENT #2 ---")
tampered_payload = '{"matched": 999}'
db.execute(
    text("UPDATE audit_log SET payload_json = :payload WHERE id = :id"),
    {"payload": tampered_payload, "id": str(e2.id)}
)
db.commit()

# 4. Verify tampered chain
res_tamper = verify_audit_chain(db)
print("\n--- TAMPER DETECTION RESULT ---")
print(f"Is Valid: {res_tamper['is_valid']}")
print(f"Broken at Sequence: {res_tamper.get('broken_at_sequence')}")
print(f"Broken Row ID: {res_tamper.get('broken_row_id')}")
print(f"Detection Reason: {res_tamper.get('reason')}")

db.close()
