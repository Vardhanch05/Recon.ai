import csv
import random
import sys
from datetime import datetime, timedelta, timezone

def generate_recon_dataset(num_records: int = 1000, output_dir: str = "data"):
    """
    Generates a mathematically synchronized, 3-file benchmark dataset:
      1. settlement_file (data/synthetic_batch_large.csv)
      2. ledger_file     (data/ledger_large.csv)
      3. ground_truth    (data/ground_truth_large.csv)
      
    Distribution:
      • ~80% Clean 1:1 Matches (Deterministic)
      • ~14% Explainable Discrepancies (MDR, GST, Surcharges, Partial Refunds, FX)
      • ~6%  Unresolvable Anomalies (Bank holdbacks, unexplained shortfalls)
    """
    random.seed(42)  # For reproducible benchmarks
    
    num_deterministic = int(num_records * 0.80)
    num_explainable = int(num_records * 0.14)
    num_unresolvable = num_records - num_deterministic - num_explainable
    
    settlements = []
    ledgers = []
    ground_truth = []
    
    base_time = datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc)
    
    current_idx = 1
    
    # -------------------------------------------------------------
    # 1. GENERATE CLEAN 80% MATCHES (Deterministic)
    # -------------------------------------------------------------
    for _ in range(num_deterministic):
        order_id = f"ORD_{current_idx:05d}"
        txn_id = f"pay_det_{current_idx:05d}"
        
        billed = round(random.uniform(500, 10000), 2)
        is_intl = random.random() < 0.15
        payment_method = random.choice(["card", "upi", "netbanking"])
        
        # Standard fee: 2% domestic, 3% intl
        fee_pct = 3.0 if is_intl else 2.0
        fee = round(billed * (fee_pct / 100.0), 2)
        settled = round(billed - fee, 2)
        
        order_time = base_time + timedelta(seconds=current_idx * 15)
        settle_time = order_time + timedelta(seconds=random.randint(0, 2))
        
        ledgers.append({
            "order_id": order_id,
            "billed_amount": billed,
            "order_timestamp": order_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "refund_amount": 0.0,
            "is_international": is_intl,
            "payment_method": payment_method
        })
        
        settlements.append({
            "gateway_txn_id": txn_id,
            "order_id": order_id,
            "settled_amount": settled,
            "settlement_timestamp": settle_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "fee_deducted": fee,
            "currency": "INR"
        })
        
        current_idx += 1

    # -------------------------------------------------------------
    # 2. GENERATE ~14% EXPLAINABLE DISCREPANCIES (AI Reasoner)
    # -------------------------------------------------------------
    explainable_types = [
        "DOMESTIC_MDR_GST",
        "INTL_MDR_GST",
        "MDR_SURCHARGE_10",
        "MDR_SURCHARGE_15",
        "PARTIAL_REFUND",
        "PARTIAL_REFUND_GST",
        "COMBINED_CAUSE",
        "FX_ROUNDING"
    ]
    
    for _ in range(num_explainable):
        order_id = f"ORD_{current_idx:05d}"
        txn_id = f"pay_exp_{current_idx:05d}"
        
        billed = round(random.uniform(1000, 8000), 2)
        discrepancy_type = random.choice(explainable_types)
        
        is_intl = False
        payment_method = "card"
        refund_amount = 0.0
        
        order_time = base_time + timedelta(seconds=current_idx * 15)
        settle_time = order_time + timedelta(seconds=random.randint(0, 2))
        
        if discrepancy_type == "DOMESTIC_MDR_GST":
            # 2% MDR + 18% GST on MDR
            fee = billed * 0.02
            gst = fee * 0.18
            settled = round(billed - fee - gst, 2)
            true_cat = "MDR_VARIANCE"
            true_cause = "2% domestic MDR with 18% GST on fee"
            
        elif discrepancy_type == "INTL_MDR_GST":
            # 3% Intl MDR + 18% GST on MDR
            is_intl = True
            fee = billed * 0.03
            gst = fee * 0.18
            settled = round(billed - fee - gst, 2)
            true_cat = "MDR_VARIANCE"
            true_cause = "3% international MDR with 18% GST on fee"
            
        elif discrepancy_type == "MDR_SURCHARGE_10":
            # 2% MDR + ₹10 flat surcharge
            fee = billed * 0.02
            settled = round(billed - fee - 10.0, 2)
            true_cat = "MDR_VARIANCE"
            true_cause = "2% MDR plus flat ₹10 gateway surcharge"
            
        elif discrepancy_type == "MDR_SURCHARGE_15":
            # 3% MDR + ₹15 flat surcharge
            is_intl = True
            fee = billed * 0.03
            settled = round(billed - fee - 15.0, 2)
            true_cat = "MDR_VARIANCE"
            true_cause = "3% international MDR plus flat ₹15 cross-border surcharge"
            
        elif discrepancy_type == "PARTIAL_REFUND":
            # ₹200 partial refund + 2% MDR
            refund_amount = round(min(billed * 0.3, 300.0), 2)
            fee = billed * 0.02
            settled = round(billed - fee - refund_amount, 2)
            true_cat = "PARTIAL_REFUND"
            true_cause = f"Partial refund of ₹{refund_amount} deducted at settlement"
            
        elif discrepancy_type == "PARTIAL_REFUND_GST":
            # ₹150 refund + 2% MDR + 18% GST
            refund_amount = 150.0
            fee = billed * 0.02
            gst = fee * 0.18
            settled = round(billed - fee - gst - refund_amount, 2)
            true_cat = "PARTIAL_REFUND"
            true_cause = "Partial refund of ₹150 combined with 18% GST on 2% MDR"
            
        elif discrepancy_type == "COMBINED_CAUSE":
            # 3% Intl MDR + 18% GST + ₹10 surcharge + ₹100 refund
            is_intl = True
            refund_amount = 100.0
            fee = billed * 0.03
            gst = fee * 0.18
            settled = round(billed - fee - gst - 10.0 - refund_amount, 2)
            true_cat = "MDR_VARIANCE"
            true_cause = "Combined 3% international MDR, 18% GST, flat surcharge, and partial refund"
            
        elif discrepancy_type == "FX_ROUNDING":
            # Minor rounding deviation of ₹0.30
            is_intl = True
            fee = billed * 0.03
            settled = round(billed - fee + 0.30, 2)
            true_cat = "FX_ROUNDING"
            true_cause = "Minor FX conversion rounding variance on international payout"

        ledgers.append({
            "order_id": order_id,
            "billed_amount": billed,
            "order_timestamp": order_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "refund_amount": refund_amount,
            "is_international": is_intl,
            "payment_method": payment_method
        })
        
        # Gateway file reports standard expected fee, exposing the discrepancy
        settlements.append({
            "gateway_txn_id": txn_id,
            "order_id": order_id,
            "settled_amount": settled,
            "settlement_timestamp": settle_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "fee_deducted": round(billed * 0.02, 2),
            "currency": "INR"
        })
        
        ground_truth.append({
            "gateway_txn_id": txn_id,
            "order_id": order_id,
            "true_category": true_cat,
            "true_cause": true_cause,
            "expected_residual_gap": 0.0
        })
        
        current_idx += 1

    # -------------------------------------------------------------
    # 3. GENERATE ~6% UNRESOLVABLE ANOMALIES (Honest Exceptions)
    # -------------------------------------------------------------
    unresolvable_causes = [
        "Unexplained bank shortfall of ₹350",
        "Arbitrary bank holdback of ₹800",
        "Unregistered chargeback deduction",
        "Unmatched cross-border ledger loss"
    ]
    
    for _ in range(num_unresolvable):
        order_id = f"ORD_{current_idx:05d}"
        txn_id = f"pay_unres_{current_idx:05d}"
        
        billed = round(random.uniform(2000, 10000), 2)
        arbitrary_gap = round(random.uniform(250, 950), 2)
        settled = round(billed - arbitrary_gap, 2)
        
        order_time = base_time + timedelta(seconds=current_idx * 15)
        settle_time = order_time + timedelta(seconds=random.randint(0, 2))
        
        ledgers.append({
            "order_id": order_id,
            "billed_amount": billed,
            "order_timestamp": order_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "refund_amount": 0.0,
            "is_international": False,
            "payment_method": "card"
        })
        
        settlements.append({
            "gateway_txn_id": txn_id,
            "order_id": order_id,
            "settled_amount": settled,
            "settlement_timestamp": settle_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "fee_deducted": round(billed * 0.02, 2),
            "currency": "INR"
        })
        
        ground_truth.append({
            "gateway_txn_id": txn_id,
            "order_id": order_id,
            "true_category": "UNRESOLVED",
            "true_cause": random.choice(unresolvable_causes),
            "expected_residual_gap": arbitrary_gap
        })
        
        current_idx += 1

    # -------------------------------------------------------------
    # WRITE CSV FILES
    # -------------------------------------------------------------
    settle_file = f"{output_dir}/synthetic_batch_large.csv"
    ledger_file = f"{output_dir}/ledger_large.csv"
    truth_file = f"{output_dir}/ground_truth_large.csv"
    
    with open(settle_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["gateway_txn_id", "order_id", "settled_amount", "settlement_timestamp", "fee_deducted", "currency"])
        writer.writeheader()
        writer.writerows(settlements)
        
    with open(ledger_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["order_id", "billed_amount", "order_timestamp", "refund_amount", "is_international", "payment_method"])
        writer.writeheader()
        writer.writerows(ledgers)
        
    with open(truth_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["gateway_txn_id", "order_id", "true_category", "true_cause", "expected_residual_gap"])
        writer.writeheader()
        writer.writerows(ground_truth)
        
    print(f"Generated {num_records} total records:")
    print(f"  - Clean Matches: {num_deterministic} (80%)")
    print(f"  - Explainable Discrepancies: {num_explainable} (14%)")
    print(f"  - Unresolvable Anomalies: {num_unresolvable} (6%)")
    print(f"\nFiles created successfully:")
    print(f"  1. {settle_file}")
    print(f"  2. {ledger_file}")
    print(f"  3. {truth_file}")

if __name__ == "__main__":
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
    generate_recon_dataset(count)
