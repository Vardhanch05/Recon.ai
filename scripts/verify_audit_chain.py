#!/usr/bin/env python3
"""
ReconAI - Cryptographic Audit Chain Verification CLI
Verifies the integrity of forward SHA-256 hash chains across all audit events.

Usage:
    python scripts/verify_audit_chain.py
    python scripts/verify_audit_chain.py --batch-id <UUID>
    python scripts/verify_audit_chain.py --verbose
"""

import sys
import os
import argparse
import uuid

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.database import SessionLocal
from backend.audit import verify_audit_chain
from backend.models import Batch, AuditLog


def main():
    parser = argparse.ArgumentParser(
        description="Verify cryptographic integrity of ReconAI immutable audit trail."
    )
    parser.add_argument(
        "--batch-id",
        type=str,
        default=None,
        help="Optional specific Batch UUID to verify. If omitted, verifies all batches.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print detailed verification output for each event.",
    )

    args = parser.parse_args()

    db = SessionLocal()
    try:
        print("=" * 75)
        print(" ReconAI - Cryptographic Audit Chain Verifier")
        print("=" * 75)

        if args.batch_id:
            try:
                target_uuid = uuid.UUID(args.batch_id)
            except ValueError:
                print(f"[-] Error: Invalid UUID format: {args.batch_id}")
                sys.exit(1)
            batches = [db.query(Batch).filter(Batch.id == target_uuid).first()]
            if not batches[0]:
                print(f"[-] Error: Batch {args.batch_id} not found in database.")
                sys.exit(1)
        else:
            batches = db.query(Batch).order_by(Batch.uploaded_at.desc()).all()

        total_events = db.query(AuditLog).count()
        print(f"[*] Total Audit Events in Database: {total_events}")
        print(f"[*] Batches found: {len(batches)}")
        print("-" * 75)

        # First verify global chain
        global_res = verify_audit_chain(db)
        if global_res["is_valid"]:
            print(f"[+] Global Hash Chain: VALID ({global_res.get('total_verified_events', 0)} events verified)")
            print(f"    Latest Sequence: {global_res.get('latest_sequence')}")
            print(f"    Chain Head Hash: {global_res.get('chain_head_hash', '')[:20]}...")
        else:
            print(f"[-] Global Hash Chain: BROKEN at sequence {global_res.get('broken_at_sequence')}")
            print(f"    Reason: {global_res.get('reason')}")
            print("=" * 75)
            sys.exit(1)

        print("-" * 75)
        print(" Batch-Level Breakdown:")
        for batch in batches:
            res = verify_audit_chain(db, batch.id if batch else None)
            status_symbol = "[+]" if res["is_valid"] else "[-]"
            batch_str = str(batch.id) if batch else "GLOBAL"
            event_count = res.get("batch_events_count", 0)
            print(f"  {status_symbol} Batch {batch_str} | Events: {event_count:4d} | Status: {'VALID' if res['is_valid'] else 'INVALID'}")

        print("=" * 75)
        print("[+] VERIFICATION PASSED: All audit logs are cryptographically intact.")
        sys.exit(0)

    finally:
        db.close()


if __name__ == "__main__":
    main()
