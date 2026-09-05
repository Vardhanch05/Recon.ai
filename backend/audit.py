import json
from datetime import datetime
from typing import Dict, Any, Union
from sqlalchemy.orm import Session
import uuid

from backend.models import AuditLog, AuditEventType

def log_audit_event(
    db: Session,
    batch_id: Union[str, uuid.UUID],
    event_type: Union[AuditEventType, str],
    actor: str,
    payload: Dict[str, Any]
) -> AuditLog:
    """
    Creates an immutable audit log entry in the database.
    """
    if isinstance(event_type, str):
        event_type = AuditEventType(event_type)
    
    if isinstance(batch_id, str):
        batch_id = uuid.UUID(batch_id)

    payload_json_str = json.dumps(payload, default=str)

    audit_entry = AuditLog(
        id=uuid.uuid4(),
        batch_id=batch_id,
        event_type=event_type,
        actor=actor,
        payload_json=payload_json_str,
        timestamp=datetime.utcnow()
    )

    db.add(audit_entry)
    db.flush()
    return audit_entry
