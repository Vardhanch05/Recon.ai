import csv # lib for CSV file operations
import io # provides in-memory text stream capabilities (StringIO) to parse raw bytes from uploads
import json # Helps convert csv to json 
import uuid # generates a unique id for each upload 
from datetime import datetime # to record when data was ingested 
from typing import List, Dict, Any, Tuple, Optional # for python type hinting
from sqlalchemy.orm import Session # needed for proper database transactions and ORM 
try:
    from backend.models import SettlementRecord, OrderLedger, AuditLog, AuditEventType
except ImportError:
    from models import SettlementRecord, OrderLedger, AuditLog, AuditEventType
# 1. Data Normalization Logic
def clean_currency(val: Any) -> float:
    """Standardizes currency strings to clean floats.
        ex:  clean_currency("₹1,200.50") -> 1200.50
             clean_currency("$49.00") -> 49.00
             clean_currency(None) -> 0.0
    """
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)

    # Stripping symbols, commas and whitespaces
    clean_str = (
        str(val).replace("₹", "").replace("$", "").replace("€", "").replace(",", "").strip()
    )
    if not clean_str:
        return 0.0
    return float(clean_str)


def parse_datetime(val: Any) -> datetime:
    """
    Robust datetime parser supporting multiple formats:
    dd/mm/YYYY | dd/mm/YYYY HH:MM | yyyy-mm-dd | natural language
    """
    if isinstance(val, datetime):
        return val
    val_str = str(val).strip()
    formats = [
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d",
        "%d-%m-%Y %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(val_str, fmt)
        except ValueError:
            continue
    return datetime.fromisoformat(val_str)

def parse_csv_stream(file_bytes: bytes) -> List[Dict[str, Any]]:
    """
        Decodes uploaded file bytes and returns a list of dicts with stripped column names and vals
        Handles both UTF-8 and Excel UTF-8-BOM (Byte Order Mark)
    """
    text_content = file_bytes.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text_content))

    rows = []
    for row in reader:
        # Strip leading/trailing whitespaces from keys and vals
        cleaned_row = {
            k.strip(): (v.strip() if isinstance(v,str) else v)
            for k, v in row.items()
            if k is not None
        }
        if any(cleaned_row.values()):
            rows.append(cleaned_row)
    return rows

# --- Settlement CSV ingestion ---

def ingest_settlement_csv(db: Session, batch_id: uuid.UUID, file_bytes: bytes) -> Tuple[int, int]:
    """
        Parses gateway settlement records and stages them in the database

        Error Isolation Rule:
          If a single row is corrupt (ex; invalid date or float), it logs an 'ingestion_error'
          event to the audit_log and continues processing remaining rows.
        returns:
          (successful_count, error_count)
    """
    rows = parse_csv_stream(file_bytes)
    success_count = 0
    event_count = 0

    for idx, row in enumerate(rows):
        try:
            # 1. Flexible Column Mapping (handles different gateway header names)
            gateway_txn_id = row.get("gateway_txn_id")or row.get("payment_id") or row.get("transaction_id")
            if not gateway_txn_id:
                raise ValueError("Missing required gateway transaction ID")
            order_id = row.get("order_id") or row.get("entity_id") or None

            # 2. Extract and sanitize monetary fields
            settled_amount = clean_currency(
                row.get("settled_amount") or row.get("amount") or row.get("net_amount")
            )
            fee_deducted = clean_currency(row.get("fee_deducted")) or row.get("fee")
            currency = row.get("currency", "INR")

            # 3. Parse Timestamp
            raw_time = row.get("settlement_timestamp") or row.get("settled_at") or row.get("created_at")
            if not raw_time:
                raise ValueError("Missing settlement timestamp")
            settlement_timestamp = parse_datetime(raw_time)

            # 4. Instantiate SettlementRecord
            record = SettlementRecord(
                batch_id=batch_id,
                gateway_txn_id=gateway_txn_id,
                order_id=order_id,
                settled_amount=settled_amount,
                settlement_timestamp=settlement_timestamp,
                fee_deducted=fee_deducted,
                currency=currency,
                raw_row_json=json.dumps(row)
            )
            db.add(record)
            success_count += 1
        except Exception as e:
            error_count += 1
            # Row-level error isolation: log failure to audit trail without crashing the batch
            audit_entry = AuditLog(
                batch_id=batch_id,
                event_type=AuditEventType.ingestion_error,
                actor="ingestion_service",
                payload_json=json.dumps({
                    "file": "settlement",
                    "row_index": idx,
                    "raw_data": row,
                    "error": str(e)
                })
            )
            db.add(audit_entry)
    db.flush()
    return success_count, error_count

# --- Order Ledger CSV ingestion ---
def ingest_ledger_csv(db: Session, batch_id: uuid.UUID, file_bytes: bytes) -> Tuple[int, int]:
    """
        Parses internal merchant order ledgers records and stages them in the database.

        returns:
            (successful_count, error_count)
    """
    rows = parse_csv_stream(file_bytes)
    success_count = 0
    error_count = 0
    for idx, row in enumerate(rows):
        try:
            # 1. Flexible Column Mapping
            order_id = row.get("order_id") or row.get("cart_id") or row.get("invoice_id")
            if not order_id:
                raise ValueError("Missing required order ID")
            # 2. Extract monetary fields
            billed_amount = clean_currency(
                row.get("billed_amount") or row.get("amount") or row.get("order_amount")
            )
            refund_amount = clean_currency(
                row.get("refund_amount") or row.get("known_refund_amount") or 0.0
            )
            # 3. Parse boolean & string flags
            raw_intl = row.get("is_international", "false")
            is_international = str(raw_intl).lower() in ("true", "1", "yes")
            payment_method = row.get("payment_method", "card")
            # 4. Parse timestamp
            raw_time = row.get("order_timestamp") or row.get("created_at") or row.get("order_date")
            if not raw_time:
                raise ValueError("Missing order timestamp")
            order_timestamp = parse_datetime(raw_time)
            # 5. Instantiate OrderLedger
            entry = OrderLedger(
                batch_id=batch_id,
                order_id=order_id,
                billed_amount=billed_amount,
                order_timestamp=order_timestamp,
                refund_amount=refund_amount,
                is_international=is_international,
                payment_method=payment_method,
                raw_row_json=json.dumps(row)
            )
            db.add(entry)
            success_count += 1
        except Exception as e:
            error_count += 1
            # Row-level error isolation: log failure to audit trail
            audit_entry = AuditLog(
                batch_id=batch_id,
                event_type=AuditEventType.ingestion_error,
                actor="ingestion_service",
                payload_json=json.dumps({
                    "file": "ledger",
                    "row_index": idx,
                    "raw_data": row,
                    "error": str(e)
                })
            )
            db.add(audit_entry)
    db.flush()
    return success_count, error_count
   