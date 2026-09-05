# UI/UX Design Brief
## Multi-Source Settlement Reconciler

---

## Design Principles

1. **Verifiable over impressive** — every AI output must show the math, not just the conclusion. Judges and accountants need to see numbers, not prose.
2. **Pipeline visibility** — the user should always know which stage the batch is in and what to do next.
3. **Human-first approval** — the UI should make it obvious that no action is final until the accountant clicks Approve.
4. **Honest exception handling** — UNRESOLVED cards should look different but not broken. They are a feature.

---

## Layout Structure

```
┌─────────────────────────────────────────────────────────┐
│  HEADER: "Settlement Reconciler" | batch selector | logo │
├─────────────────────────────────────────────────────────┤
│  PIPELINE STEPPER:                                        │
│  [1. Upload ✓] → [2. Match ✓] → [3. AI Review ●] → [4. Done] │
├───────────────────────┬─────────────────────────────────┤
│  LEFT PANEL           │  RIGHT PANEL                    │
│  MatchRateSummaryCard │  ExceptionList / AuditLogViewer │
│  UploadPanel          │  (tabbed)                       │
└───────────────────────┴─────────────────────────────────┘
```

---

## Component Specs

### UploadPanel
- Two drag-and-drop zones: "Settlement File (CSV)" and "Order Ledger (CSV)"
- File name shown after selection
- "Upload & Process" CTA button — disabled until both files selected
- Advanced toggle: "Timestamp tolerance (seconds)" — default 2, hidden by default

### Pipeline Stepper
- Four steps: Upload → Match → AI Reasoning → Complete
- Current step highlighted with a spinner if in progress
- Completed steps show a checkmark
- Blocked steps are greyed out and non-clickable

### MatchRateSummaryCard
- Three stat blocks side by side:
  - "80% Deterministic" (green)
  - "14% AI-Resolved" (purple)
  - "6% Unresolved" (amber)
- Throughput timer: "Processed in 8.3s"
- Ingestion error warning if count > 0: "⚠ 1 row skipped — see audit log"
- Stats show "--" until the relevant stage completes

### ReasoningCard
- Header row: Transaction ID | Discrepancy Amount | Category badge | Confidence badge
- Confidence badge colors:
  - 0.70–0.99 → green
  - 0.30–0.69 → amber
  - 0.0 → red (UNRESOLVED)
- Hypothesis text: single paragraph, plain language
- "Show Calculation" toggle → expands math table:

```
┌────────────────────────────────────┐
│ Billed Amount      ₹1,000.00       │
│ Fee (3.0%)         ₹30.00          │
│ GST on Fee (18%)   ₹5.40           │
│ Flat Surcharge     ₹10.00          │
│ Expected Settlement ₹954.60        │
│ Actual Settlement   ₹954.60        │
│ Residual Gap        ₹0.00 ✓        │
└────────────────────────────────────┘
```

- Residual gap = 0.00 shows ✓ in green; non-zero shows the amount in amber/red
- Approve button: solid green, full width
- Reject button: outlined red, full width
- After approval: card background turns light green, buttons replaced with "✓ Approved by [user]"
- After rejection: card background turns light red, shows "✗ Rejected — Manual Review Required" + override note if present
- UNRESOLVED cards: amber background, no approve/reject for the AI card (accountant must handle manually), shows the list of attempted hypotheses

### AuditLogViewer
- Table: Timestamp | Actor | Event Type | Description
- Filter bar: event type dropdown + date range picker
- Monospace font for payload details (expandable row)
- No edit controls — read-only indicator in header

---

## Color System

| Meaning | Color |
|---|---|
| Deterministic / system | Slate gray |
| AI-resolved / in progress | Purple (#6c5ce7) |
| Approved / success | Green (#00b894) |
| Rejected / manual | Red (#d63031) |
| Low confidence / warning | Amber (#e17055) |
| Unresolved | Amber background (#ffeaa7) |
| Neutral / background | White / light gray |

---

## Key UX Rules

- Never show a spinner without a status message explaining what's happening
- The math table is not optional — it must be one click away on every AI-resolved card
- UNRESOLVED is never shown as an error state — use neutral amber, not red
- The pipeline stepper drives the "what to do next" UX — don't hide it
- The [Approve] button should be the most visually prominent action on each card
- 409 responses (double-click) show a brief non-intrusive toast, not a full error page
