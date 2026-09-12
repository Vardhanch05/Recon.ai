# App Flow Document
## Multi-Source Settlement Reconciler

---

## High-Level User Journey

The application provides an intuitive, accountant-friendly financial workflow:

```
[ Upload CSVs ] ──► [ Deterministic Match (80%) ] ──► [ AI Reasoner (14%) ] ──► [ Review & Approve ] ──► [ Journal Posted ]
```

---

## Step-by-Step Pipeline Flow

### 1. Ingestion Stage
1. User lands on the Recon.ai dashboard.
2. User drags and drops `settlement.csv` and `ledger.csv` into the `UploadPanel`.
3. User selects optional fallback timestamp tolerance (default: 2s).
4. User clicks **"Upload & Ingest Batch"** $\rightarrow$ `POST /batches/upload`.
5. Backend parses files, sanitizes dirty currency symbols, logs any row-level ingestion errors to `audit_log`, and commits records.
6. The UI transitions to the **"Uploaded"** state and unlocks the deterministic matching trigger.

### 2. Deterministic Matching Stage
1. User clicks **"Run Matching"** $\rightarrow$ `POST /batches/{id}/run-matching`.
2. Backend executes two-pass deterministic matching in <200ms:
   - Pass 1: Order ID lookup + fee sanity verification.
   - Pass 2: Timestamp and fee-adjusted amount fallback lookup.
3. Summary stats immediately update:
   - **44 of 55 records matched deterministically (80%)**.
   - **11 exceptions** routed for AI discrepancy analysis.
4. Pipeline stepper marks Step 2 complete and unlocks Step 3.

### 3. AI Discrepancy Reasoning Stage
1. User clicks **"Run AI Reasoning"** $\rightarrow$ `POST /batches/{id}/run-reasoning`.
2. Backend validates batch status atomically and launches the async LLM reasoner in `BackgroundTasks`.
3. Frontend begins polling `GET /batches/{id}/summary` every 2 seconds.
4. The LLM processes exception records, invoking `calculate_difference()` to verify arithmetic against standard fee/GST/refund tiers.
5. Server-side `validate_card()` computes mathematically bounded confidence scores.
6. When reasoning completes, `ExceptionList` populates with interactive `ReasoningCard` items.

### 4. Human Review & Approval Gate
1. Accountant reviews each card in `ExceptionList`:
   - **Discrepancy Category Badge** (`MDR_VARIANCE`, `PARTIAL_REFUND`, `FX_ROUNDING`, `DOMESTIC_MDR`, `UNRESOLVED`).
   - **Confidence Score Pill** (Green: $\ge 0.70$, Amber: $0.30 - 0.69$, Red: $0.00$).
   - **Hypothesis Explanation**.
   - **"Show Calculation Breakdown"** expandable table verifying expected vs settled amounts and residual gap.
2. Accountant actions:
   - **Approve**: Clicks **Approve** $\rightarrow$ `POST /reconciliation/{id}/approve`. Server validates status atomically, marks record `human_approved`, creates journal posting, and emits an immutable audit event. Card transitions to a green approved state.
   - **Reject**: Clicks **Reject** $\rightarrow$ opens modal for optional accountant notes $\rightarrow$ `POST /reconciliation/{id}/reject`. Card transitions to a rejected manual review state.
   - **Concurrency Guard**: If double-clicked, UI catches HTTP 409 and displays a non-blocking toast notification.

### 5. Audit Log Inspection
1. Accountant switches to the **Audit Log** tab.
2. Streams real-time events (`ingestion_error`, `match`, `llm_call`, `human_approval`, `human_rejection`, `journal_posted`).
3. User filters events by event type and reviews JSON payloads.

### 6. Live Accuracy Evaluation (Demo / Judge Flow)
1. User clicks the **"Accuracy Report"** button in the header.
2. Frontend calls `GET /batches/{id}/accuracy-report?ground_truth_path=data/ground_truth.csv`.
3. A modal renders a live confusion matrix:
   - Explainable Accuracy: **7 / 7 (100%)**
   - Unresolvable Accuracy: **3 / 3 (100%)**
   - Overall Accuracy: **10 / 10 non-trivial records (100%)**
