# Research Document
## Multi-Source Settlement Reconciler

---

## 1. Problem Validation

### How Razorpay Settlement Works

- Razorpay settles funds to merchants via NEFT/RTGS as a single lumped credit
- Settlement cycle: T+2 (2 business days after transaction date)
- Each settlement covers multiple orders, net of:
  - MDR (Merchant Discount Rate): ~2% for domestic cards, ~3% for international cards
  - GST on MDR: 18%
  - Refund deductions (if any refunds were processed)
  - Flat gateway surcharges (payment-method specific)
- Razorpay provides a settlement CSV report with transaction-level detail

### The Reconciliation Problem

- Merchant's internal ledger records `billed_amount` (what the customer paid)
- Settlement file records `settled_amount` (what Razorpay actually transferred, after deductions)
- The gap between these is not a simple subtraction — it depends on: payment method, whether order was international, whether a refund was processed, and which fee tier applies
- Different payment methods (card vs UPI vs netbanking) have different MDR rates
- This makes batch reconciliation non-trivial for any order with a discrepancy

### Existing Tooling Gap

- Razorpay offers integrations with Tally, Zoho Books, QuickBooks
- These integrations handle clean matches (order_id → settle amount, no discrepancy)
- They do not explain *why* a settlement amount differs when it doesn't match exactly
- Finance teams currently handle exceptions manually — looking at each record individually

---

## 2. Fee Structure (Razorpay Public Pricing — Approximate)

| Payment Method | MDR (approximate) |
|---|---|
| Domestic cards | 2.0% |
| International cards | 3.0% |
| UPI | 0% (currently) |
| Netbanking | 1.5–2.5% (bank dependent) |
| GST on MDR | 18% of MDR fee |
| Flat surcharges | Varies by plan/method |

These figures are used as defaults in `known_fee_schedule`. The system treats the fee schedule as a configurable JSON input — the demo ships with Razorpay defaults.

---

## 3. LLM Tool-Calling Approach

### Why Tool-Calling for Arithmetic

LLMs are unreliable at arithmetic in free text. Known failure modes:
- Floating-point inconsistency (e.g., 1000 * 0.03 = 29.99999 in prose)
- Percentage vs decimal confusion (fee_pct=0.03 vs fee_pct=3.0)
- Confident but wrong arithmetic especially on multi-step calculations

The design forces the LLM to use a deterministic Python function for all math. The LLM's only job is to select which parameters to pass (reasoning), not to compute the result.

### Why Not LangGraph for the Core Loop

LangGraph adds value for stateful, branching, multi-agent flows. For a single LLM call + single tool call per record, it adds framework overhead without benefit. The decision: plain LangChain `.batch()` for parallelism, no LangGraph for the core reasoning step.

LangGraph *would* add value for a multi-hypothesis retry loop (try hypothesis 1 → check residual_gap → retry with hypothesis 2 → ...). This is a valid enhancement if time allows.

---

## 4. Confidence Scoring Approach

### Why Not LLM Self-Reported Confidence

LLM self-reported confidence scores are:
- Not calibrated (0.9 confidence does not mean 90% accuracy)
- RLHF-biased toward high confidence
- Indefensible when a judge asks "how do you know it's 87% confident?"

### The Residual Gap Approach

The confidence score is derived from `residual_gap` after the `calculate_difference` tool call. This is:
- A verifiable number (the math is shown in the UI)
- Independent of the LLM's self-assessment
- Defensible: "confidence is 0.94 because the residual gap is ₹0.03"

Limitation: a gap of 0.0 means the numbers close, not that the hypothesis is causally correct. Two different fee combinations can produce the same settled amount. The accuracy report against the ground-truth answer key is the check for causal correctness.

---

## 5. Synthetic Dataset Design Rationale

### Why Pre-Built Ground Truth

Reporting accuracy against your own system's output is circular. Building the ground-truth answer key *before* the reasoner means the system is evaluated against an independent standard, not post-hoc plausibility.

### Why Unresolvable Records Are Included

The track bar explicitly requires "an honest exception list." A system that force-fits every record into a category is less valuable than one that knows when it doesn't know. The 3 unresolvable records are designed with discrepancy amounts outside any plausible fee-math range (e.g., ₹200+ gaps that no combination of 2–3% MDR + 18% GST produces).

### Timestamp Design

The `settlement_timestamp` in the synthetic data uses the original transaction timestamp (not the T+2 credit-posting time). This is consistent with real Razorpay settlement file format. The ±2 second fallback tolerance is a deduplication guard, not a T+2 window.

---

## 6. Prior Art / Comparable Systems

- **Bank reconciliation tools** (e.g., Xero, QuickBooks auto-match): deterministic only, no discrepancy reasoning
- **Stripe Sigma / Stripe Reconciliation**: query-based, no AI reasoning layer
- **General LLM finance agents**: typically RAG over documents, not tool-calling over structured financial math
- **This system's differentiator**: combines deterministic matching (fast, accurate for clean records) with LLM reasoning for exceptions, enforces math via tool-calling, requires human approval, and produces a verifiable accuracy report
