import json
import hashlib
import threading
from datetime import datetime, timezone
from typing import Dict, Any, Union, Optional
from sqlalchemy.orm import Session
import uuid

from backend.models import AuditLog, AuditChainHead, AuditEventType

# Process-level serialization lock for SQLite environments
_CHAIN_LOCK = threading.Lock()

GENESIS_HASH = "0" * 64

def canonical_json_dumps(obj: Any) -> str:
    """
    Serializes a dictionary or JSON-compatible object to a canonical string
    with sorted keys to guarantee deterministic cryptographic hashing.
    """
    if isinstance(obj, str):
        try:
            parsed = json.loads(obj)
            return json.dumps(parsed, sort_keys=True, separators=(",", ":"), default=str)
        except Exception:
            return obj
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def compute_audit_hash(
    prev_hash: str,
    batch_id: Optional[Union[str, uuid.UUID]],
    event_type: str,
    actor: str,
    timestamp_iso: str,
    canonical_payload: str
) -> str:
    """
    Computes deterministic SHA-256 hash for an audit log event.
    """
    batch_str = str(batch_id) if batch_id else "null"
    raw_payload = f"{prev_hash}:{batch_str}:{event_type}:{actor}:{timestamp_iso}:{canonical_payload}"
    return hashlib.sha256(raw_payload.encode("utf-8")).hexdigest()


def log_audit_event(
    db: Session,
    batch_id: Optional[Union[str, uuid.UUID]],
    event_type: Union[AuditEventType, str],
    actor: str,
    payload: Dict[str, Any]
) -> AuditLog:
    """
    Creates an immutable, cryptographically hash-chained audit log entry.
    Atomic execution guarantees that AuditLog insert and AuditChainHead update
    succeed or roll back together without chain forking under concurrency.
    """
    if isinstance(event_type, str):
        event_type = AuditEventType(event_type)
    
    if isinstance(batch_id, str):
        batch_id = uuid.UUID(batch_id)

    canonical_payload_str = canonical_json_dumps(payload)
    event_timestamp = datetime.now(timezone.utc).replace(tzinfo=None)
    timestamp_iso = event_timestamp.isoformat()

    with _CHAIN_LOCK:
        # Check dialect for PostgreSQL row-level lock vs SQLite
        dialect_name = db.bind.dialect.name if db.bind else ""
        query = db.query(AuditChainHead).filter(AuditChainHead.id == 1)
        if dialect_name == "postgresql":
            query = query.with_for_update()

        head = query.first()
        if not head:
            # Initialize Genesis Head singleton
            head = AuditChainHead(
                id=1,
                current_hash=GENESIS_HASH,
                sequence_num=0,
                updated_at=event_timestamp
            )
            db.add(head)
            db.flush()

        prev_hash = head.current_hash
        next_seq = head.sequence_num + 1

        # Compute SHA-256 current hash
        current_hash = compute_audit_hash(
            prev_hash=prev_hash,
            batch_id=batch_id,
            event_type=event_type.value,
            actor=actor,
            timestamp_iso=timestamp_iso,
            canonical_payload=canonical_payload_str
        )

        audit_entry = AuditLog(
            id=uuid.uuid4(),
            batch_id=batch_id,
            sequence_num=next_seq,
            prev_hash=prev_hash,
            current_hash=current_hash,
            event_type=event_type,
            actor=actor,
            payload_json=canonical_payload_str,
            timestamp=event_timestamp
        )

        db.add(audit_entry)

        # Update singleton head in same transaction
        head.current_hash = current_hash
        head.sequence_num = next_seq
        head.updated_at = event_timestamp

        db.flush()

    return audit_entry


def verify_audit_chain(
    db: Session,
    batch_id: Optional[Union[str, uuid.UUID]] = None
) -> Dict[str, Any]:
    """
    Cryptographically verifies the audit log chain from sequence 1 to N.
    Stops at the first broken link or payload tamper.
    """
    if isinstance(batch_id, str):
        batch_id = uuid.UUID(batch_id)

    # Fetch global chain ordered by sequence_num
    events = db.query(AuditLog).order_by(AuditLog.sequence_num.asc()).all()
    if not events:
        return {
            "is_valid": True,
            "total_verified_events": 0,
            "message": "Audit chain is empty (no events)."
        }

    prev_hash_expected = GENESIS_HASH

    for idx, e in enumerate(events):
        seq = e.sequence_num
        
        # 1. Verify link continuity
        if e.prev_hash != prev_hash_expected:
            return {
                "is_valid": False,
                "broken_at_sequence": seq,
                "broken_row_id": str(e.id),
                "reason": f"Chain link break: prev_hash '{e.prev_hash}' does not match expected previous hash '{prev_hash_expected}'."
            }

        # 2. Recompute current hash to detect in-place payload tampering
        expected_current = compute_audit_hash(
            prev_hash=e.prev_hash,
            batch_id=e.batch_id,
            event_type=e.event_type.value if hasattr(e.event_type, "value") else str(e.event_type),
            actor=e.actor,
            timestamp_iso=e.timestamp.isoformat(),
            canonical_payload=canonical_json_dumps(e.payload_json)
        )

        if e.current_hash != expected_current:
            return {
                "is_valid": False,
                "broken_at_sequence": seq,
                "broken_row_id": str(e.id),
                "reason": f"Cryptographic tamper detected: current_hash '{e.current_hash}' does not match recomputed payload hash '{expected_current}'."
            }

        prev_hash_expected = e.current_hash

    # If batch_id was specified, also report how many events belong to this batch
    batch_events_count = sum(1 for e in events if e.batch_id == batch_id) if batch_id else len(events)

    return {
        "is_valid": True,
        "total_verified_events": len(events),
        "batch_events_count": batch_events_count,
        "latest_sequence": events[-1].sequence_num,
        "head_hash": events[-1].current_hash,
        "message": "Audit chain is cryptographically intact and unbroken."
    }
