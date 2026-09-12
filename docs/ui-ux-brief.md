# UI/UX Design Brief
## Multi-Source Settlement Reconciler

---

## Design Principles

1. **Mathematical Transparency**: Every AI-suggested conclusion is backed by an expandable calculation breakdown showing exact billed, fee, GST, refund, expected settlement, and residual gap figures.
2. **Deterministic Clarity & Pipeline Stepper**: Clear 4-stage pipeline stepper guiding the accountant through Ingestion, Matching, AI Reasoning, and Human Review.
3. **Strict Human Gate**: Unresolved records cannot be approved to post funds; approved cards provide immediate visual confirmation of journal posting.
4. **Honest Exception Demarcation**: Unresolvable records are highlighted with distinct amber tags, transparently explaining that no standard fee schedule closes the residual gap.

---

## Component Hierarchy & Specifications

### 1. `<Header />`
- Branding: "Recon.ai" with Live Settlement Engine badge.
- Action Buttons: "New Batch", "View Audit Trail", and "Accuracy Report".
- Real-time batch ID indicator and status indicator pill.

### 2. `<PipelineStepper />`
- 4-Step Interactive Visual Flow:
  1. **Upload & Ingest** (Completed / In-Progress / Pending)
  2. **Deterministic Match** (Triggers `/run-matching` on click)
  3. **AI Reasoning** (Triggers `/run-reasoning` with progress spinner)
  4. **Human Review & Posting** (Status indicator)

### 3. `<UploadPanel />`
- Dual Drag-and-Drop Dropzones for `Settlement CSV` and `Ledger CSV`.
- File size indicators and clear-file buttons.
- Advanced settings toggle for `Timestamp Tolerance (seconds)`.
- Primary CTA: "Upload & Ingest Batch" with animated loading state.

### 4. `<MatchRateSummaryCard />`
- 3 Primary Metric Cards:
  - **Deterministic Match Rate** (e.g., 80.0% / 44 records) in Emerald Green.
  - **AI Discrepancy Resolved** (e.g., 12.7% / 7 records) in Indigo Purple.
  - **Unresolved Exceptions** (e.g., 5.5% / 3 records) in Amber Warning.
- Throughput Benchmarking: "Throughput: 4,200 ms" badge.
- Row Error Alert banner when `ingestion_error_count > 0`.

### 5. `<ReasoningCard />` & `<ExceptionList />`
- Filter Bar: All Exceptions, AI Resolved, Unresolved, Approved, Rejected.
- Card Header: Transaction ID, Discrepancy Amount, Category Badge, and Mathematical Confidence Pill.
- Body: Formatted AI hypothesis narrative.
- Calculation Breakdown Drawer: Expandable breakdown table with checkmark indicator when `residual_gap == 0.00`.
- Action Bar:
  - Solid Green **Approve** button (triggers journal entry).
  - Outlined Red **Reject** button (opens manual review modal).
  - Post-action states: Green "Approved & Posted" / Red "Rejected".

### 6. `<AuditLogViewer />`
- Full-width immutable event stream.
- Filterable by `event_type` (`ingestion_error`, `match`, `llm_call`, `human_approval`, `human_rejection`, `journal_posted`).
- Expandable JSON payload viewer with syntax formatting.

### 7. `<AccuracyReportModal />`
- Modal displaying live confusion matrix:
  - True Positives (Explainable Discrepancies).
  - True Negatives (Correctly Flagged Unresolved).
  - False Positives & False Negatives.
  - Category-by-category precision breakdown.

---

## Design Tokens & Theme

- **Background**: Deep slate financial dark mode (`#0f172a` / `#1e293b`).
- **Surface & Cards**: Glassmorphism cards with subtle border highlight (`rgba(255, 255, 255, 0.08)`).
- **Accents**:
  - Success / Match: Emerald (`#10b981`)
  - AI Reasoning: Indigo / Violet (`#6366f1` / `#8b5cf6`)
  - Warning / Unresolved: Amber (`#f59e0b`)
  - Rejection / Error: Rose / Red (`#ef4444`)
  - Primary Action: Blue (`#3b82f6`)
- **Typography**: Inter / Outfit sans-serif with monospace styling for financial values and transaction IDs.
