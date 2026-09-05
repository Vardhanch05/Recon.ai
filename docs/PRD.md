# Product Requirements Document (PRD)
## Multi-Source Settlement Reconciler
### Razorpay AI Builder Buildathon — Track 4: AI Finance Controller

---

## 1. Problem Statement

Razorpay merchants receive a single lumped NEFT credit covering hundreds of orders, net of MDR fees (~2% domestic, ~3% international), 18% GST on those fees, and refund deductions. Finance teams must manually reconcile this credit against their internal order ledger — a process that is error-prone, time-consuming, and completely manual for any discrepancy that doesn't match a simple rule.

Existing integrations (Tally, Zoho, QuickBooks via Razorpay) handle clean deterministic matches but provide no reasoning capability for ambiguous discrepancies. There is no tooling that explains *why* a settlement amount differs from the expected order amount and surfaces that explanation for human review.

---

## 2. Product Goal

Build an AI-powered settlement reconciliation agent that:
- Automatically matches ~80% of records deterministically (no AI needed for clean matches)
- Uses an LLM reasoning agent to explain the remaining ~14% of ambiguous discrepancies
- Honestly flags ~6% of records as unresolvable rather than force-fitting an explanation
- Surfaces all reasoning for human approval before any ledger posting occurs
- Reports a verifiable match rate and exception list — not cherry-picked results

---

## 3. Target User

Finance controller / accountant at a Razorpay merchant company who:
- Receives a Razorpay settlement file (CSV) every T+2 cycle
- Maintains an internal order ledger
- Currently reconciles manually or via basic integrations
- Needs to approve any automated categorization before it affects books

---

## 4. Track Bar (Success Criteria)

The Razorpay Buildathon Track 4 bar is:
> "Build an agent that closes one finance-ops loop across a 50+ record batch of synthetic data, reporting its match rate and the exceptions it could not resolve. Throughput plus measured accuracy plus an honest exception list. One cherry-picked match proves nothing."

This system must satisfy:
- **Throughput**: Process 50+ records end-to-end within a demo timeframe (<15s for LLM reasoning pass)
- **Measured accuracy**: Report match rate against a pre-built ground-truth answer key, not post-hoc
- **Honest exception list**: Correctly flag unresolvable records as UNRESOLVED rather than inventing explanations

---

## 5. Core Features

### F1 — Batch Ingestion
- Upload settlement CSV + order ledger CSV via a web UI
- Parse, validate, and normalize both files into the database
- Surface ingestion errors (malformed rows) in the batch summary with a count
- Reject duplicate batches with an explicit confirmation prompt

### F2 — Deterministic Matching (80% of records)
- Primary match: order_id exact match
- Fallback match: fee-adjusted amount + timestamp window (when order_id absent)
- Tag every exception with a routing_reason so the LLM has context
- Near-instant (<1s for 50 records)

### F3 — LLM Discrepancy Reasoning (14% of records)
- For each exception, LLM proposes a fee/tax/refund hypothesis
- LLM calls `calculate_difference()` tool to verify arithmetic — never does math in free text
- Supports combined-cause hypotheses (MDR + refund + FX in one tool call)
- Server-side `validate_card()` overrides any LLM confidence/category inconsistency with `compute_confidence()` output

### F4 — Reasoning Cards
- One card per exception: hypothesis text, math breakdown table, confidence score, category
- Category: MDR_VARIANCE / PARTIAL_REFUND / FX_ROUNDING / UNRESOLVED
- Confidence score derived from residual_gap — defensible under questioning

### F5 — Human Approval Workflow
- Accountant approves or rejects each card
- Nothing posts to the ledger without explicit approval
- Atomic concurrency guard on both approve and reject (returns 409 on double-action)
- Rejected cards record reviewer identity and optional override note

### F6 — Audit Trail
- Every event logged immutably: ingestion, match, LLM call, human approval/rejection, journal posting
- Searchable by event type and date range
- Read-only — no editing or deletion

### F7 — Accuracy Reporting
- `/accuracy-report` endpoint joins reasoning_cards against a pre-uploaded ground-truth CSV
- Returns a confusion matrix: correct categorizations vs. total explainable records
- Live-verifiable during the demo

---

## 6. Out of Scope (for this build)

- Multi-gateway support (single gateway format assumed)
- Real Razorpay API integration (synthetic data only)
- Multi-user role management (single accountant role)
- Mobile UI
- Historical batch comparison / trend reporting

---

## 7. Constraints

- Synthetic dataset: 50–60 records with documented ground truth
- LLM reasoning pass must complete in <15 seconds for demo
- All AI-suggested actions require human approval before DB posting
- Confidence score must be mathematically derived, not LLM self-reported

---

## 8. Non-Goals

- Replacing the human accountant — the system assists, not decides
- Guaranteeing 100% match rate — honest exception reporting is a feature
- Real-time streaming reconciliation — batch-oriented only
