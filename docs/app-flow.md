# App Flow Document
## Multi-Source Settlement Reconciler

---

## Overview

The application has one primary user flow: an accountant uploads two CSV files, runs a two-stage reconciliation pipeline, reviews AI-generated reasoning cards, and approves or rejects each one. The entire flow is designed to be completable in a single session.

---

## Flow 1: Upload & Ingest

```
Accountant lands on dashboard
  → Sees UploadPanel with two file inputs: "Settlement File" and "Order Ledger"
  → Selects settlement.csv
  → Selects ledger.csv
  → Optionally adjusts timestamp tolerance (advanced setting, default 2s)
  → Clicks "Upload & Process"
  → POST /batches/upload fires
  → Backend parses both CSVs, writes to DB
  → If ingestion errors: dashboard shows "X rows skipped — see audit log"
  → batch.status = 'uploaded'
  → "Run Matching" button becomes enabled
```

---

## Flow 2: Deterministic Matching

```
Accountant clicks "Run Matching"
  → POST /batches/{id}/run-matching fires (synchronous)
  → Loading spinner shown
  → Backend runs matching engine:
      - order_id primary match
      - fee-adjusted amount+timestamp fallback
      - exceptions tagged with routing_reason
  → Response returns
  → MatchRateSummaryCard updates:
      - "44 of 55 matched automatically (80%)"
      - "11 exceptions routed to AI review"
  → batch.status = 'matching_complete'
  → "Run AI Reasoning" button becomes enabled
```

---

## Flow 3: LLM Reasoning

```
Accountant clicks "Run AI Reasoning"
  → POST /batches/{id}/run-reasoning fires
  → Returns job_id immediately (async)
  → Frontend begins polling GET /batches/{id}/summary every 2 seconds
  → Progress indicator: "Analyzing 11 exceptions..."
  → Backend processes exceptions in parallel via LangChain .batch()
      - Each exception: build context → LLM call → tool call → validate_card → write DB
  → When batch.status = 'reasoning_complete':
      - MatchRateSummaryCard finalizes:
          "80% deterministic | 12.7% AI-resolved | 6% unresolved"
          "Total processing time: 8.3 seconds"
      - ExceptionList populates with reasoning cards
      - "Review Exceptions" section scrolls into view
```

---

## Flow 4: Exception Review & Approval

```
Accountant sees ExceptionList
  → Each ReasoningCard shows:
      - Transaction ID + discrepancy amount (e.g., "₹34.20 shortfall")
      - Hypothesis text (e.g., "Matches 18% GST on 3% international MDR fee")
      - Calculation breakdown table (expandable):
          Billed amount: ₹1000.00
          Fee (3%):       ₹30.00
          GST on fee:     ₹5.40
          Expected:       ₹964.60
          Actual:         ₹964.60
          Residual gap:   ₹0.00
      - Confidence badge: 0.94 (green) / 0.52 (amber) / 0.00 (red UNRESOLVED)
      - Category tag: MDR_VARIANCE / PARTIAL_REFUND / FX_ROUNDING / UNRESOLVED
      - [Approve] [Reject] buttons

  → Accountant reviews the math table (not just the prose)
  → Clicks [Approve]:
      - POST /reconciliation/{id}/approve fires
      - Atomic DB update: status = 'human_approved'
      - Card renders with green "Approved" badge
      - Journal entry posted
      - Audit log entry written

  → OR clicks [Reject]:
      - Modal prompts: "Add a note? (optional)"
      - POST /reconciliation/{id}/reject fires
      - Card renders with red "Rejected — Manual Review Required" badge
      - No journal entry posted

  → If double-click: second request gets 409, UI shows "Already actioned"
```

---

## Flow 5: Audit Log Review

```
Accountant scrolls to AuditLogViewer (or clicks "View Audit Log" tab)
  → Sees chronological event stream:
      [2024-01-15 14:30:01] system    | match           | order_id:ORD-001 → ledger:L-001
      [2024-01-15 14:30:02] llm       | llm_call        | exception:EXC-003, hypothesis:MDR_VARIANCE
      [2024-01-15 14:31:15] user:u001 | human_approval  | result:REC-007, card:RC-003
      [2024-01-15 14:31:22] system    | journal_posted  | result:REC-007
  → Can filter by event type (match / llm_call / human_approval / etc.)
  → Can filter by date range
  → Read-only — no edit controls
```

---

## Flow 6: Accuracy Report (Demo/Judge Flow)

```
Accountant (or judge) clicks "View Accuracy Report"
  → GET /batches/{id}/accuracy-report fires
  → Backend joins reasoning_cards.suggested_category against ground_truth.csv
  → Dashboard shows confusion matrix:
      Explainable records:  7 of 7 correctly categorized (100%)
      Unresolvable records: 3 of 3 correctly flagged UNRESOLVED (100%)
      Overall accuracy:     10 of 10 non-trivial records correct
  → This is the live verifiable accuracy claim
```

---

## State Transitions

```
batch.status:
  uploaded → matching_complete → reasoning_complete
                                      ↓
                              (per reconciliation_result)
  pending → human_approved → journal_posted
         → human_rejected  → manual_handling
```

---

## Error States

| Scenario | UI Behavior |
|---|---|
| CSV parse error | "X rows could not be parsed — check audit log for details" |
| LLM API timeout | Card shows "AI reasoning unavailable — manual review required" |
| Double approve/reject | Toast: "This card was already actioned" (409 handled silently) |
| Duplicate batch upload | Modal: "A batch with this name already exists. Overwrite?" |
