# Master Context Prompt — Track 4: Multi-Source Settlement Reconciler
### Razorpay AI Builder Buildathon

Paste this entire document as the first message in a new chat to continue this project with full context.

---

## Who I Am / What I'm Building

I'm building a project for the Razorpay AI Builder Hackathon/Buildathon, specifically for **Track 4: AI Finance Controller**. The track's official bar is: *"Build an agent that closes one finance-ops loop across a 50+ record batch of synthetic data, reporting its match rate and the exceptions it could not resolve. Throughput plus measured accuracy plus an honest exception list. One cherry-picked match proves nothing."*

My chosen idea is the **Multi-Source Settlement Reconciler**, matching their named example direction ("Multi-source reconciliation").

---

## The Real-World Problem (Validated)

This is confirmed as a genuine, well-documented pain point for Razorpay merchants specifically (not an internal Razorpay engineering problem):

- When Razorpay settles funds to a merchant, it arrives as a single lumped NEFT credit covering hundreds of orders, net of ~2% MDR (merchant discount rate/gateway fee), 18% GST charged on that fee, and any refund deductions — turning what should be a simple order-by-order match into an "unpacking" problem.
- Settlement typically happens on a T+2 cycle (2 business days after transaction), and different gateways format settlement reports differently, so cross-referencing against internal order ledgers requires careful, often manual handling.
- Finance teams currently do this largely by hand or via basic Tally/Zoho/QuickBooks integrations that Razorpay already offers — but those appear to only handle clean, deterministic matching, not reasoning through *ambiguous* discrepancies (e.g., "why is this settlement short by ₹34.20 — is it a fee, a partial refund, an FX rounding issue, or an actual error?").
- **This is my key differentiator**: existing tooling (Razorpay's own Tally/Zoho/QuickBooks integrations) does deterministic order-ID/fee matching, but doesn't appear to do LLM-reasoned explanation of ambiguous exceptions with a human-approval workflow. That gap is what this project targets.

---

## The Architecture (Already Designed — Do Not Redesign From Scratch)

**Pipeline, in order:**
1. **Ingestion** — Parse settlement file + internal order ledger into structured DB tables (deterministic).
2. **Deterministic Matching** — Match records on order_id (primary) or amount+timestamp within a tolerance window (fallback). Expected to clear ~80% of records instantly, with no AI involved.
3. **Exception Routing** — Unmatched/ambiguous records (multiple candidates, no order_id, amount mismatch) get routed to a queue — no forced 1:1 matching.
4. **LLM Discrepancy Reasoner** — For each exception, the LLM proposes a hypothesis (e.g., "this looks like 18% GST on a 3% international MDR fee") and MUST verify it via a callable `calculate_difference()` tool rather than doing arithmetic in free text. The tool accepts `fee_pct`, `gst_on_fee_pct`, `flat_surcharge`, `refund_amount`, and `fx_adjustment` — covering single-cause and combined-cause hypotheses in one call. If no hypothesis produces a small enough residual gap, it honestly outputs `UNRESOLVED` rather than force-fitting an explanation. A server-side `validate_card()` function overrides any LLM-reported confidence/category values with ones computed from `residual_gap` before writing to DB.
5. **Reasoning Card Generation** — Structured output per exception: hypothesis text, calculation breakdown (a real math table), a confidence score, and a category (MDR_VARIANCE / PARTIAL_REFUND / FX_ROUNDING / UNRESOLVED).
6. **Human Approval** — An accountant approves or rejects each card. Nothing is posted to the ledger without this step — the AI never has final authority over money. This is intentional and should NOT be automated away — it's the safety boundary the track's bar explicitly rewards.
7. **Ledger Posting + Audit Trail** — Approved cards trigger journal entries; every match, LLM call, and human decision is logged immutably from the start.

**Data model:** PostgreSQL (relational/ACID-appropriate for financial ledger data) with tables: `settlement_records`, `order_ledger`, `reconciliation_results`, `reasoning_cards`, `audit_log`, `batches`.

**Tech stack decided so far:** FastAPI backend, PostgreSQL, React frontend, LLM with function/tool-calling (not LangGraph for the core reasoning step — see automation section below).

---

## Confidence Score Logic (Finalized — Do Not Redesign)

The confidence score is derived **mathematically from the tool's `residual_gap` output**, never self-reported by the LLM (LLM self-reported confidence is unreliable and not defensible under judge questioning). Current formula uses linear interpolation across four bands:

```python
def compute_confidence(residual_gap: float) -> tuple[float, str]:
    gap = abs(residual_gap)
    if gap <= 0.05:
        confidence = 0.99 - (gap / 0.05) * 0.04       # scales 0.99 → 0.95
        status = "resolved"
    elif gap <= 0.50:
        confidence = 0.94 - ((gap - 0.05) / 0.45) * 0.24   # scales 0.94 → 0.70
        status = "resolved"
    elif gap <= 5.00:   # <-- THIS THRESHOLD IS STILL BEING CALIBRATED, SEE BELOW
        confidence = 0.69 - ((gap - 0.50) / 4.50) * 0.39   # scales 0.69 → 0.30
        status = "low_confidence"
    else:
        confidence = 0.0
        status = "unresolved"
    return round(confidence, 2), status
```

**Open calibration question (unresolved, needs a decision):** The upper threshold (currently ₹5.00, was considering ₹1.00) for the "low confidence but still reported" band should NOT be picked arbitrarily — it needs to be calibrated against the actual residual gaps produced by the genuine discrepancy records in the synthetic dataset once built (see Evaluation Dataset section below). Generate the real discrepancy records first, run them through `calculate_difference`, see what gaps naturally occur, and set the threshold just above the largest gap among genuinely-correct explanations and just below the smallest gap among deliberately-unresolvable records.

---

## Evaluation / Synthetic Dataset Design (Required, Not Yet Built)

Need 50–60 records with a deliberate, documented mix:
- ~40 records (80%): clean 1:1 matches, no discrepancy.
- ~7 records (14%): genuine explainable discrepancies, varied across: domestic MDR, international MDR, GST-on-fee, partial refund, flat gateway surcharge, and at least one combined-cause case (to stress-test the reasoner).
- ~3 records (6%): deliberately unresolvable (e.g., a data-entry error), so the system is forced to honestly flag `UNRESOLVED`.
- **Critical requirement:** keep a separate, hidden ground-truth answer key (true cause per record) generated *before* building the reasoner, so accuracy can be reported honestly against known answers — not just "the explanation sounds plausible."

---

## Automation / LangChain-LangGraph Decision (Already Debated, Conclusion Reached)

Conclusion from prior discussion — **do not re-litigate this without new information**:
- The core reasoning step (Stage 4) as currently scoped is a single LLM call + single tool call per record, no branching or looping — LangGraph adds no real value here and adds unnecessary framework overhead/debugging complexity for a hackathon timeframe.
- **One legitimate LangGraph use case identified but NOT YET BUILT:** turning Stage 4 into a genuine multi-hypothesis retry loop — try hypothesis 1, check residual_gap, if not close enough try hypothesis 2 (e.g., combined causes), up to N attempts, then give up. This is a real stateful/conditional loop and would both genuinely improve reasoning quality AND make for a stronger demo ("watch it try three hypotheses before landing on the right one"). This is the one open enhancement worth pursuing if time allows.
- Plain LangChain's `.batch()` method (not LangGraph) is worth using to run exception records through the LLM concurrently rather than sequentially — directly helps the throughput target (~10 seconds for the exception batch) without adding real complexity.
- Human approval gate (Stage 6) is a legitimate conceptual fit for LangGraph's human-in-the-loop interrupt pattern if the team wants the full pipeline modeled as one traceable state machine — optional, not required.

---

## Known Open Questions / Unresolved Decisions

1. **Confidence threshold calibration** (₹5.00 vs ₹1.00 vs data-derived) — needs the synthetic dataset built first to decide properly.
2. **What happens when two different fee-combination hypotheses both produce a near-zero residual gap?** No tie-breaking rule defined yet. Interim approach: flag `requires_human_review: true` and note the ambiguity in `hypothesis_text` prose (e.g., "Two hypotheses both close the gap: domestic MDR 2% or international MDR 3% + surcharge — manual verification required"). Do NOT attempt to output multiple hypotheses as separate objects — the current `reasoning_cards` schema is singular (one `hypothesis_text`, one `calculation_breakdown` per card).
3. **Live-demo fallback if the LLM API is slow/down** — recommended mitigation: pre-compute the exception batch on your demo dataset before the demo and cache `reasoning_cards` rows in DB. Show the live upload → deterministic matching flow live, then reveal pre-cached cards. Keep a 2–3 record live example available if a judge wants to see the real-time path.
4. **Scope of `known_fee_schedule`** — treat as a configurable JSON input that ships with a Razorpay-defaults file. Demo should show the file being loaded so judges don't ask "how does it know the fee rates?"
5. **How to frame the "6% unresolved" number in the pitch** — lead with it as evidence of honesty: "the system correctly refused to explain 3 records where no known fee pattern fits, flagging them for manual review rather than fabricating a plausible-sounding explanation." This directly satisfies the track bar's "honest exception list" requirement.
6. **`settlement_timestamp` assumption — resolved.** Decision: `settlement_timestamp` is the original transaction timestamp echoed back by the gateway (not the T+2 credit-posting time). This makes the ±2 second fallback tolerance meaningful as a deduplication guard. This is documented in LLD §3.1 and §4.1. If your actual settlement file uses credit-posting timestamps instead, remove the timestamp condition from the fallback and rely on order_id + fee-adjusted amount only.

---

## What I Want Help With Next

[Fill this in when you paste this into the new chat — e.g., "help me write the actual synthetic dataset," "help me implement the multi-hypothesis retry loop," "help me build the FastAPI ingestion endpoint," "help me design the pitch deck," etc.]

---

## Ground Rules for the New Chat

- Don't re-explain or re-justify decisions already marked "finalized" above unless new information changes them — build forward from this state.
- Flag any numbers, thresholds, or metrics as estimates/design choices, not verified facts, unless we've explicitly calibrated them against real data.
- If asked to modify the confidence-scoring logic or architecture, treat the version above as the current baseline to modify, not something to redesign from scratch.
