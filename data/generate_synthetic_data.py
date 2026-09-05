import csv
import os
import random
from datetime import datetime, timedelta

def generate_datasets():
    os.makedirs("data", exist_ok=True)

    base_time = datetime(2026, 9, 1, 9, 0, 0)
    
    settlements = []
    ledgers = []
    ground_truths = []

    order_counter = 1000

    # ─────────────────────────────────────────────────────────────
    # 1. 44 Clean Deterministic Matches (80% of 55)
    # ─────────────────────────────────────────────────────────────
    for i in range(1, 45):
        order_counter += 1
        txn_id = f"pay_det_{i:03d}"
        order_id = f"ORD_{order_counter}"
        txn_time = base_time + timedelta(minutes=i * 5)
        
        billed_amount = round(random.choice([500.0, 1000.0, 1500.0, 2500.0, 5000.0]), 2)
        fee_pct = 2.0  # standard domestic MDR
        fee_deducted = round(billed_amount * (fee_pct / 100.0), 2)
        settled_amount = round(billed_amount - fee_deducted, 2)

        # 40 have explicit order_id in settlement, 4 test fallback matching (missing order_id)
        settle_order_id = order_id if i <= 40 else ""

        settlements.append({
            "gateway_txn_id": txn_id,
            "order_id": settle_order_id,
            "settled_amount": settled_amount,
            "settlement_timestamp": txn_time.isoformat() + "Z",
            "fee_deducted": fee_deducted,
            "currency": "INR"
        })

        ledgers.append({
            "order_id": order_id,
            "billed_amount": billed_amount,
            "order_timestamp": txn_time.isoformat() + "Z",
            "refund_amount": 0.00,
            "is_international": False,
            "payment_method": random.choice(["card", "upi", "netbanking"])
        })

    # ─────────────────────────────────────────────────────────────
    # 2. 8 Explainable Discrepancies (AI Reasoner scope)
    # ─────────────────────────────────────────────────────────────
    explainable_cases = [
        # Case 1: Domestic MDR (2%) + 18% GST on MDR
        {
            "desc": "Domestic 2% MDR + 18% GST",
            "billed": 1000.00,
            "nominal_fee": 20.00,
            "fee_pct": 2.0,
            "gst_pct": 18.0,
            "surcharge": 0.0,
            "refund": 0.0,
            "intl": False,
            "category": "MDR_VARIANCE",
            "cause": "2% domestic MDR with 18% GST"
        },
        # Case 2: International MDR (3%) + 18% GST on MDR
        {
            "desc": "International 3% MDR + 18% GST",
            "billed": 2000.00,
            "nominal_fee": 40.00,
            "fee_pct": 3.0,
            "gst_pct": 18.0,
            "surcharge": 0.0,
            "refund": 0.0,
            "intl": True,
            "category": "MDR_VARIANCE",
            "cause": "3% international MDR with 18% GST"
        },
        # Case 3: Flat Gateway Surcharge (₹10) + 2% MDR
        {
            "desc": "Flat ₹10 Surcharge + 2% MDR",
            "billed": 1500.00,
            "nominal_fee": 30.00,
            "fee_pct": 2.0,
            "gst_pct": 0.0,
            "surcharge": 10.0,
            "refund": 0.0,
            "intl": False,
            "category": "MDR_VARIANCE",
            "cause": "2% MDR plus flat ₹10 gateway surcharge"
        },
        # Case 4: Partial Refund deduction (₹200) + 2% fee
        {
            "desc": "Partial refund of ₹200 + 2% fee",
            "billed": 1000.00,
            "nominal_fee": 20.00,
            "fee_pct": 2.0,
            "gst_pct": 0.0,
            "surcharge": 0.0,
            "refund": 200.0,
            "intl": False,
            "category": "PARTIAL_REFUND",
            "cause": "Partial customer refund of ₹200 deducted at settlement"
        },
        # Case 5: 3% International card fee + flat ₹15 surcharge
        {
            "desc": "Intl 3% fee + ₹15 surcharge",
            "billed": 3000.00,
            "nominal_fee": 60.00,
            "fee_pct": 3.0,
            "gst_pct": 0.0,
            "surcharge": 15.0,
            "refund": 0.0,
            "intl": True,
            "category": "MDR_VARIANCE",
            "cause": "3% international card processing fee plus ₹15 flat cross-border surcharge"
        },
        # Case 6: Partial refund ₹150 + 18% GST on 2% MDR
        {
            "desc": "Partial refund + GST on MDR",
            "billed": 1200.00,
            "nominal_fee": 24.00,
            "fee_pct": 2.0,
            "gst_pct": 18.0,
            "surcharge": 0.0,
            "refund": 150.0,
            "intl": False,
            "category": "PARTIAL_REFUND",
            "cause": "Partial refund of ₹150 combined with 18% GST on 2% MDR"
        },
        # Case 7: Combined Cause: 3% Intl MDR + 18% GST + ₹10 surcharge + ₹100 refund
        {
            "desc": "Combined MDR + GST + Surcharge + Refund",
            "billed": 2500.00,
            "nominal_fee": 50.00,
            "fee_pct": 3.0,
            "gst_pct": 18.0,
            "surcharge": 10.0,
            "refund": 100.0,
            "intl": True,
            "category": "MDR_VARIANCE",
            "cause": "Combined 3% international MDR, 18% GST, flat surcharge, and ₹100 refund"
        },
        # Case 8: Minor FX rounding variance (₹0.20)
        {
            "desc": "FX Rounding adjustment",
            "billed": 1000.00,
            "nominal_fee": 20.00,
            "fee_pct": 3.0,
            "gst_pct": 18.0,
            "surcharge": 0.0,
            "refund": 0.0,
            "intl": True,
            "category": "FX_ROUNDING",
            "cause": "Minor FX conversion rounding adjustment on international settlement"
        }
    ]

    for idx, case in enumerate(explainable_cases, 1):
        order_counter += 1
        txn_id = f"pay_exp_{idx:03d}"
        order_id = f"ORD_{order_counter}"
        txn_time = base_time + timedelta(hours=5, minutes=idx * 5)

        billed = case["billed"]
        fee = billed * (case["fee_pct"] / 100.0)
        gst = fee * (case["gst_pct"] / 100.0)
        expected = billed - fee - gst - case["surcharge"] - case["refund"]
        settled = round(expected, 2)

        settlements.append({
            "gateway_txn_id": txn_id,
            "order_id": order_id,
            "settled_amount": settled,
            "settlement_timestamp": txn_time.isoformat() + "Z",
            "fee_deducted": case["nominal_fee"],  # Nominal base fee in settlement CSV triggers sanity check gap!
            "currency": "INR"
        })

        ledgers.append({
            "order_id": order_id,
            "billed_amount": billed,
            "order_timestamp": txn_time.isoformat() + "Z",
            "refund_amount": case["refund"] if case["refund"] > 0 else 0.0,
            "is_international": case["intl"],
            "payment_method": "card"
        })

        ground_truths.append({
            "gateway_txn_id": txn_id,
            "order_id": order_id,
            "true_category": case["category"],
            "true_cause": case["cause"],
            "expected_residual_gap": 0.00
        })

    # ─────────────────────────────────────────────────────────────
    # 3. 3 Unresolvable Discrepancies (Large nonsensical gaps)
    # ─────────────────────────────────────────────────────────────
    unresolvable_cases = [
        {"billed": 2000.00, "nominal_fee": 40.00, "settled": 1650.00, "cause": "Unexplained bank shortfall of ₹350"},
        {"billed": 5000.00, "nominal_fee": 100.00, "settled": 4200.00, "cause": "Arbitrary bank holdback of ₹800"},
        {"billed": 1500.00, "nominal_fee": 30.00, "settled": 980.00, "cause": "Unregistered chargeback deduction"}
    ]

    for idx, case in enumerate(unresolvable_cases, 1):
        order_counter += 1
        txn_id = f"pay_unres_{idx:03d}"
        order_id = f"ORD_{order_counter}"
        txn_time = base_time + timedelta(hours=8, minutes=idx * 5)

        settlements.append({
            "gateway_txn_id": txn_id,
            "order_id": order_id,
            "settled_amount": case["settled"],
            "settlement_timestamp": txn_time.isoformat() + "Z",
            "fee_deducted": case["nominal_fee"],
            "currency": "INR"
        })

        ledgers.append({
            "order_id": order_id,
            "billed_amount": case["billed"],
            "order_timestamp": txn_time.isoformat() + "Z",
            "refund_amount": 0.00,
            "is_international": False,
            "payment_method": "card"
        })

        ground_truths.append({
            "gateway_txn_id": txn_id,
            "order_id": order_id,
            "true_category": "UNRESOLVED",
            "true_cause": case["cause"],
            "expected_residual_gap": round(case["billed"] - case["nominal_fee"] - case["settled"], 2)
        })

    # Write files
    def write_csv(filepath, rows, fieldnames):
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    write_csv("data/synthetic_batch.csv", settlements, ["gateway_txn_id", "order_id", "settled_amount", "settlement_timestamp", "fee_deducted", "currency"])
    write_csv("data/ledger.csv", ledgers, ["order_id", "billed_amount", "order_timestamp", "refund_amount", "is_international", "payment_method"])
    write_csv("data/ground_truth.csv", ground_truths, ["gateway_txn_id", "order_id", "true_category", "true_cause", "expected_residual_gap"])

    print(f"Generated {len(settlements)} settlement records ({len(ledgers)} ledger rows, {len(ground_truths)} ground truth rows).")

if __name__ == "__main__":
    generate_datasets()
