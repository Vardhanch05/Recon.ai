import io
import csv
import json
from datetime import datetime
from typing import Tuple, List, Dict, Any
from dateutil import parser as date_parser

def parse_iso_or_custom_datetime(date_str: str) -> datetime:
    """Safely parse various datetime formats from CSV files."""
    if not date_str or not date_str.strip():
        raise ValueError("Empty datetime string")
    return date_parser.parse(date_str.strip())


def parse_settlement_csv(content_bytes: bytes) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Parses settlement CSV bytes.
    Returns:
        valid_rows: list of normalized dicts
        error_rows: list of malformed row error dicts
    """
    valid_rows = []
    error_rows = []

    text_stream = io.StringIO(content_bytes.decode("utf-8-sig", errors="replace"))
    reader = csv.DictReader(text_stream)

    # Normalize header names (lowercase, stripped)
    if reader.fieldnames:
        reader.fieldnames = [f.strip().lower() for f in reader.fieldnames]

    row_index = 1
    for row in reader:
        row_index += 1
        raw_copy = dict(row)
        try:
            # 1. Gateway Txn ID (required)
            gateway_txn_id = (
                row.get("gateway_txn_id") or row.get("txn_id") or row.get("transaction_id") or row.get("id")
            )
            if not gateway_txn_id or not gateway_txn_id.strip():
                raise ValueError("Missing gateway_txn_id")
            gateway_txn_id = gateway_txn_id.strip()

            # 2. Order ID (optional)
            order_id = row.get("order_id")
            order_id = order_id.strip() if order_id and order_id.strip() else None

            # 3. Settled Amount (required decimal)
            amount_str = row.get("settled_amount") or row.get("amount") or row.get("net_amount")
            if not amount_str:
                raise ValueError("Missing settled_amount")
            settled_amount = round(float(amount_str.strip().replace(",", "")), 2)

            # 4. Settlement Timestamp (required datetime)
            ts_str = row.get("settlement_timestamp") or row.get("timestamp") or row.get("created_at")
            if not ts_str:
                raise ValueError("Missing settlement_timestamp")
            settlement_timestamp = parse_iso_or_custom_datetime(ts_str)

            # 5. Fee Deducted (optional)
            fee_str = row.get("fee_deducted") or row.get("fee") or row.get("fees")
            fee_deducted = round(float(fee_str.strip().replace(",", "")), 2) if fee_str and fee_str.strip() else None

            # 6. Currency (default INR)
            currency = (row.get("currency") or "INR").strip().upper()

            valid_rows.append({
                "gateway_txn_id": gateway_txn_id,
                "order_id": order_id,
                "settled_amount": settled_amount,
                "settlement_timestamp": settlement_timestamp,
                "fee_deducted": fee_deducted,
                "currency": currency,
                "raw_row_json": json.dumps(raw_copy)
            })
        except Exception as e:
            error_rows.append({
                "row_index": row_index,
                "raw_data": raw_copy,
                "error": str(e)
            })

    return valid_rows, error_rows


def parse_ledger_csv(content_bytes: bytes) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Parses internal merchant ledger CSV bytes.
    Returns:
        valid_rows: list of normalized dicts
        error_rows: list of malformed row error dicts
    """
    valid_rows = []
    error_rows = []

    text_stream = io.StringIO(content_bytes.decode("utf-8-sig", errors="replace"))
    reader = csv.DictReader(text_stream)

    if reader.fieldnames:
        reader.fieldnames = [f.strip().lower() for f in reader.fieldnames]

    row_index = 1
    for row in reader:
        row_index += 1
        raw_copy = dict(row)
        try:
            # 1. Order ID (required)
            order_id = row.get("order_id") or row.get("id") or row.get("order_reference")
            if not order_id or not order_id.strip():
                raise ValueError("Missing order_id")
            order_id = order_id.strip()

            # 2. Billed Amount (required decimal)
            amount_str = row.get("billed_amount") or row.get("amount") or row.get("total_amount")
            if not amount_str:
                raise ValueError("Missing billed_amount")
            billed_amount = round(float(amount_str.strip().replace(",", "")), 2)

            # 3. Order Timestamp (required datetime)
            ts_str = row.get("order_timestamp") or row.get("timestamp") or row.get("created_at")
            if not ts_str:
                raise ValueError("Missing order_timestamp")
            order_timestamp = parse_iso_or_custom_datetime(ts_str)

            # 4. Refund Amount (optional)
            refund_str = row.get("refund_amount") or row.get("refund") or row.get("refunds")
            refund_amount = round(float(refund_str.strip().replace(",", "")), 2) if refund_str and refund_str.strip() else None

            # 5. International flag (default False)
            intl_val = str(row.get("is_international") or row.get("international") or "").strip().lower()
            is_international = intl_val in ("true", "1", "yes", "t", "y")

            # 6. Payment method (optional)
            payment_method = (row.get("payment_method") or row.get("method") or "card").strip().lower()

            valid_rows.append({
                "order_id": order_id,
                "billed_amount": billed_amount,
                "order_timestamp": order_timestamp,
                "refund_amount": refund_amount,
                "is_international": is_international,
                "payment_method": payment_method,
                "raw_row_json": json.dumps(raw_copy)
            })
        except Exception as e:
            error_rows.append({
                "row_index": row_index,
                "raw_data": raw_copy,
                "error": str(e)
            })

    return valid_rows, error_rows
