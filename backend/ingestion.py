import csv
import io
import json
import uuid
from datetime import datetime
from typing import List, Dict, Any, Tuple, Optional
from sqlalchemy.orm import Session

try:
    from backend.models import SettlementRecord, OrderLedger, AuditLog, AuditEventType
except ImportError:
    from models import SettlementRecord, OrderLedger, AuditLog, AuditEventType


# ---------------------------------------------------------------------------
# 1. Data Normalization Helpers
# ---------------------------------------------------------------------------

def clean_currency(val: Any) -> float:
    """Standardizes currency strings to clean floats.
    Handles symbols (₹, $, €, £, ¥, ₩), ISO codes, commas, accounting negatives
    (e.g., ($500)), and explicit negative signs.
    """
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    
    val_str = str(val).strip()
    if not val_str:
        return 0.0
    
    is_negative = False
    if val_str.startswith("(") and val_str.endswith(")"):
        is_negative = True
        val_str = val_str[1:-1].strip()
    elif "-" in val_str:
        is_negative = True
        val_str = val_str.replace("-", "").strip()

    for symbol in ["₹", "$", "€", "£", "¥", "₩", ",", "INR", "USD", "EUR", "GBP"]:
        val_str = val_str.replace(symbol, "")
    val_str = val_str.strip()

    if not val_str:
        return 0.0

    parsed = float(val_str)
    return -parsed if is_negative else parsed


def parse_datetime(val: Any) -> datetime:
    """
    Robust datetime parser supporting multiple formats.
    """
    if isinstance(val, datetime):
        return val
    val_str = str(val).strip()
    formats = [
        "%Y-%m-%dT%H:%M:%SZ",
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
    Decodes uploaded file bytes and returns a list of dicts with stripped column names.
    Handles UTF-8 and Excel UTF-8-BOM.
    """
    text_content = file_bytes.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text_content))
    rows = []
    for row in reader:
        cleaned_row = {
            k.strip(): (v.strip() if isinstance(v, str) else v)
            for k, v in row.items()
            if k is not None
        }
        if any(cleaned_row.values()):
            rows.append(cleaned_row)
    return rows


# ---------------------------------------------------------------------------
# 2. Pure-parse functions (no DB writes) — used by batches.py upload route
# ---------------------------------------------------------------------------

def parse_settlement_csv(file_bytes: bytes) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Parses settlement CSV bytes into validated row dicts.
    Returns: (valid_rows, error_rows)
    Does NOT write to the database.
    """
    rows = parse_csv_stream(file_bytes)
    valid_rows: List[Dict[str, Any]] = []
    error_rows: List[Dict[str, Any]] = []

    for idx, row in enumerate(rows):
        try:
            # Flexible column mapping
            gateway_txn_id = (
                row.get("gateway_txn_id") or row.get("payment_id") or row.get("transaction_id")
            )
            if not gateway_txn_id:
                raise ValueError("Missing required gateway transaction ID")

            order_id = row.get("order_id") or row.get("entity_id") or None

            settled_amount = clean_currency(
                row.get("settled_amount") or row.get("amount") or row.get("net_amount")
            )

            # FIX A8: Check is not None and not empty string explicitly so 0.0 is not lost
            raw_fee = row.get("fee_deducted") if row.get("fee_deducted") is not None else row.get("fee")
            fee_deducted: Optional[float] = clean_currency(raw_fee) if (raw_fee is not None and str(raw_fee).strip() != "") else None

            currency = row.get("currency", "INR")

            raw_time = (
                row.get("settlement_timestamp") or row.get("settled_at") or row.get("created_at")
            )
            if not raw_time:
                raise ValueError("Missing settlement timestamp")
            settlement_timestamp = parse_datetime(raw_time)

            valid_rows.append({
                "gateway_txn_id": gateway_txn_id,
                "order_id": order_id,
                "settled_amount": settled_amount,
                "settlement_timestamp": settlement_timestamp,
                "fee_deducted": fee_deducted,
                "currency": currency,
                "raw_row_json": json.dumps(row),
            })
        except Exception as e:
            error_rows.append({"row_index": idx, "raw_data": row, "error": str(e)})

    return valid_rows, error_rows


def parse_ledger_csv(file_bytes: bytes) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Parses ledger CSV bytes into validated row dicts.
    Returns: (valid_rows, error_rows)
    Does NOT write to the database.
    """
    rows = parse_csv_stream(file_bytes)
    valid_rows: List[Dict[str, Any]] = []
    error_rows: List[Dict[str, Any]] = []

    for idx, row in enumerate(rows):
        try:
            order_id = row.get("order_id") or row.get("cart_id") or row.get("invoice_id")
            if not order_id:
                raise ValueError("Missing required order ID")

            billed_amount = clean_currency(
                row.get("billed_amount") or row.get("amount") or row.get("order_amount")
            )
            # FIX A13: Explicit None/empty check for refund_amount
            raw_refund = row.get("refund_amount") if row.get("refund_amount") is not None else row.get("known_refund_amount")
            refund_amount = clean_currency(raw_refund) if (raw_refund is not None and str(raw_refund).strip() != "") else 0.0

            raw_intl = row.get("is_international", "false")
            is_international = str(raw_intl).lower() in ("true", "1", "yes")
            payment_method = row.get("payment_method", "card")

            raw_time = (
                row.get("order_timestamp") or row.get("created_at") or row.get("order_date")
            )
            if not raw_time:
                raise ValueError("Missing order timestamp")
            order_timestamp = parse_datetime(raw_time)

            valid_rows.append({
                "order_id": order_id,
                "billed_amount": billed_amount,
                "order_timestamp": order_timestamp,
                "refund_amount": refund_amount,
                "is_international": is_international,
                "payment_method": payment_method,
                "raw_row_json": json.dumps(row),
            })
        except Exception as e:
            error_rows.append({"row_index": idx, "raw_data": row, "error": str(e)})

    return valid_rows, error_rows


# ---------------------------------------------------------------------------
# 3. DB-writing ingest functions (used internally / legacy paths)
# ---------------------------------------------------------------------------

def ingest_settlement_csv(db: Session, batch_id: uuid.UUID, file_bytes: bytes) -> Tuple[int, int]:
    """
    Parses gateway settlement records and stages them in the database.
    Error Isolation: corrupt rows are logged to audit_log without crashing the batch.
    Returns: (successful_count, error_count)
    """
    rows = parse_csv_stream(file_bytes)
    success_count = 0
    error_count = 0  # FIX C2: was mislabeled as event_count

    for idx, row in enumerate(rows):
        try:
            gateway_txn_id = (
                row.get("gateway_txn_id") or row.get("payment_id") or row.get("transaction_id")
            )
            if not gateway_txn_id:
                raise ValueError("Missing required gateway transaction ID")

            order_id = row.get("order_id") or row.get("entity_id") or None

            settled_amount = clean_currency(
                row.get("settled_amount") or row.get("amount") or row.get("net_amount")
            )

            # FIX A8: properly handle zero-fee entries and empty string
            raw_fee = row.get("fee_deducted") if row.get("fee_deducted") is not None else row.get("fee")
            fee_deducted: Optional[float] = clean_currency(raw_fee) if (raw_fee is not None and str(raw_fee).strip() != "") else None

            currency = row.get("currency", "INR")

            raw_time = (
                row.get("settlement_timestamp") or row.get("settled_at") or row.get("created_at")
            )
            if not raw_time:
                raise ValueError("Missing settlement timestamp")
            settlement_timestamp = parse_datetime(raw_time)

            record = SettlementRecord(
                batch_id=batch_id,
                gateway_txn_id=gateway_txn_id,
                order_id=order_id,
                settled_amount=settled_amount,
                settlement_timestamp=settlement_timestamp,
                fee_deducted=fee_deducted,
                currency=currency,
                raw_row_json=json.dumps(row),
            )
            db.add(record)
            success_count += 1
        except Exception as e:
            error_count += 1
            audit_entry = AuditLog(
                batch_id=batch_id,
                event_type=AuditEventType.ingestion_error,
                actor="ingestion_service",
                payload_json=json.dumps({
                    "file": "settlement",
                    "row_index": idx,
                    "raw_data": row,
                    "error": str(e),
                }),
            )
            db.add(audit_entry)

    db.flush()
    return success_count, error_count


def ingest_ledger_csv(db: Session, batch_id: uuid.UUID, file_bytes: bytes) -> Tuple[int, int]:
    """
    Parses internal merchant order ledger records and stages them in the database.
    Returns: (successful_count, error_count)
    """
    rows = parse_csv_stream(file_bytes)
    success_count = 0
    error_count = 0

    for idx, row in enumerate(rows):
        try:
            order_id = row.get("order_id") or row.get("cart_id") or row.get("invoice_id")
            if not order_id:
                raise ValueError("Missing required order ID")

            billed_amount = clean_currency(
                row.get("billed_amount") or row.get("amount") or row.get("order_amount")
            )
            # FIX A13: Explicit None/empty check for refund_amount
            raw_refund = row.get("refund_amount") if row.get("refund_amount") is not None else row.get("known_refund_amount")
            refund_amount = clean_currency(raw_refund) if (raw_refund is not None and str(raw_refund).strip() != "") else 0.0

            raw_intl = row.get("is_international", "false")
            is_international = str(raw_intl).lower() in ("true", "1", "yes")
            payment_method = row.get("payment_method", "card")

            raw_time = (
                row.get("order_timestamp") or row.get("created_at") or row.get("order_date")
            )
            if not raw_time:
                raise ValueError("Missing order timestamp")
            order_timestamp = parse_datetime(raw_time)

            entry = OrderLedger(
                batch_id=batch_id,
                order_id=order_id,
                billed_amount=billed_amount,
                order_timestamp=order_timestamp,
                refund_amount=refund_amount,
                is_international=is_international,
                payment_method=payment_method,
                raw_row_json=json.dumps(row),
            )
            db.add(entry)
            success_count += 1
        except Exception as e:
            error_count += 1
            audit_entry = AuditLog(
                batch_id=batch_id,
                event_type=AuditEventType.ingestion_error,
                actor="ingestion_service",
                payload_json=json.dumps({
                    "file": "ledger",
                    "row_index": idx,
                    "raw_data": row,
                    "error": str(e),
                }),
            )
            db.add(audit_entry)

    db.flush()
    return success_count, error_count