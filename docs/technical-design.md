# Technical Design Document
## Multi-Source Settlement Reconciler

---

## 1. System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                             React 19 Frontend                               │
│  [Header] → [PipelineStepper] → [UploadPanel] → [MatchRateSummaryCard]      │
│  [ExceptionList] ───► [ReasoningCard] (Math Breakdown & Approval Gate)      │
│  [AuditLogViewer] & [AccuracyReportModal] (Ground-Truth Confusion Matrix)   │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ HTTP / REST (Vite Proxy / CORS)
┌──────────────────────────────────────▼──────────────────────────────────────┐
│                              FastAPI Backend                                │
│  ┌─────────────────────────┐  ┌───────────────────────┐  ┌────────────────┐ │
│  │   Batches Router        │  │ Reconciliation Router │  │ Reports Router │ │
│  │ (/batches/upload,       │  │ (/run-matching,       │  │ (/accuracy-    │ │
│  │  /summary, /audit-log)  │  │  /run-reasoning,      │  │   report)      │ │
│  │                         │  │  /approve, /reject)   │  │                │ │
│  └────────────┬────────────┘  └───────────┬───────────┘  └───────┬────────┘ │
│               │                           │                      │          │
│  ┌────────────▼───────────────────────────▼──────────────────────▼────────┐ │
│  │                 Ingestion, Matching & Reasoning Services               │ │
│  │  • Deterministic Matching Engine (80% auto-match rate)                 │ │
│  │  • Parallel LLM Reasoner with tool-calling verification                │ │
│  │  • Immutable Audit Logger (Lifecycle ORM Event Listeners)              │ │
│  └────────────────────────────────────┬───────────────────────────────────┘ │
└───────────────────────────────────────┼─────────────────────────────────────┘
                                        │
┌───────────────────────────────────────▼─────────────────────────────────────┐
│                   Database Layer (PostgreSQL / SQLite)                      │
│  batches | settlement_records | order_ledger | reconciliation_results       │
│  exception_candidates | reasoning_cards | audit_log                         │
└───────────────────────────────────────┬─────────────────────────────────────┘
                                        │
                         ┌──────────────▼──────────────┐
                         │   LLM Provider (Groq/OpenAI)│
                         │   + calculate_difference    │
                         │     Deterministic Tool      │
                         └─────────────────────────────┘
```

---

## 2. Core Subsystems & Services

### 2.1 CSV Ingestion Engine (`backend/ingestion.py`)
- **Fault-Tolerant Parsing**: Cleans currency strings, validates RFC 3339 / ISO timestamps, and detects required columns.
- **Row-Level Error Isolation**: Malformed rows are captured and summarized in `ingestion_error` audit logs without interrupting the ingestion of valid transactions.
- **Deduplication**: Enforces distinct gateway transaction IDs per batch before DB commit.

### 2.2 Deterministic Matching Engine (`backend/matching.py`)
The deterministic engine processes records without invoking AI tokens:
1. **Primary Path (Order ID Match)**:
   - Queries `order_ledger` by exact `order_id`.
   - If match found: checks fee sanity (`abs(billed - fee_deducted - settled) < 0.01`). If fee matches or is omitted, records status as `matched_deterministic` (`order_id_match`).
   - If fee discrepancy is detected, tags as `amount_mismatch` and routes to exception queue.
2. **Fallback Path (Fee-Adjusted Amount & Timestamp)**:
   - Used when `order_id` is missing.
   - Searches candidate ledger records where `abs((billed - fee_deducted) - settled) < 0.01` within the configurable `timestamp_tolerance_seconds` window.
   - Single match $\rightarrow$ `matched_deterministic` (`amount_match`).
   - Multiple matches $\rightarrow$ records candidates in `exception_candidates` and routes as `ambiguous_multiple`.
   - Zero matches $\rightarrow$ routes as `no_match`.

### 2.3 LLM Discrepancy Reasoner (`backend/reasoning.py`)
- **Arithmetic Integrity via Tool-Calling**:
  - LLMs are restricted from performing math in free-text prose.
  - The LLM receives structured exception metadata and is instructed to call the server-side `calculate_difference()` tool.
  - Tool calculates exact expected settlements, GST-on-MDR, refunds, and residual gap:
  $$\text{Expected} = \text{Billed} - \text{Fee} - \text{GST} - \text{Surcharge} - \text{Refund} + \text{FX}$$
  $$\text{Residual Gap} = \text{Settled} - \text{Expected}$$
- **Server-Side Validation Guard (`validate_card`)**:
  - Overwrites LLM confidence with mathematically computed confidence score.
  - Automatically converts hypotheses with high residual gaps to `UNRESOLVED`.

### 2.4 Human Approval & Ledger Safety (`backend/routes/reconciliation.py`)
- **Strict Concurrency Protection**:
  - Direct atomic SQL UPDATE: `WHERE id = :result_id AND status = 'matched_ai_resolved'`.
  - Zero double-posting risk: immediate HTTP 409 Conflict if row was already actioned.
  - Hard constraint: `UNRESOLVED` records cannot be approved to post funds to the ledger.
- **Audit Logging**:
  - Generates immutable `human_approval` and `journal_posted` records in the same atomic transaction.

### 2.5 Query Performance & Optimization
- **Eager Loading Strategy**: Uses `joinedload` on single foreign keys (`settlement_record`, `order_ledger`, `reasoning_card`) and `selectinload` on one-to-many collections (`exception_candidates`) to eliminate N+1 database queries.
- **Dedicated Count Queries**: Eliminates pagination cartesian product inflations.

---

## 3. API Route Structure

| Route | Method | Purpose | Status Code |
|---|---|---|---|
| `/batches/upload` | POST | Ingests settlement and ledger CSV files | 200 OK / 409 Conflict |
| `/batches/{id}/summary` | GET | Returns pipeline status, match rates, and throughput | 200 OK |
| `/batches/{id}/run-matching` | POST | Triggers deterministic matching engine pass | 200 OK |
| `/batches/{id}/run-reasoning` | POST | Triggers asynchronous LLM reasoning pass on exceptions | 202 Accepted / 409 Conflict |
| `/batches/{id}/exceptions` | GET | Returns paginated reasoning cards for accountant review | 200 OK |
| `/reconciliation/{id}/approve` | POST | Human accountant approves card & posts journal entry | 200 OK / 409 Conflict |
| `/reconciliation/{id}/reject` | POST | Human accountant rejects card with optional review note | 200 OK / 409 Conflict |
| `/batches/{id}/audit-log` | GET | Returns immutable audit event stream | 200 OK |
| `/batches/{id}/accuracy-report` | GET | Computes confusion matrix against ground truth | 200 OK |
| `/health` | GET | Health check verifying API & database connectivity | 200 OK |

---

## 4. Failure Modes & Defenses

| Potential Failure | System Defense |
|---|---|
| Malformed / Dirty CSV rows | Regex sanitization + row-level error catching $\rightarrow$ logs `ingestion_error` without failing batch |
| Duplicate CSV batch upload | Duplicate detection check + 409 confirmation prompt |
| LLM arithmetic hallucination | Tool-calling restriction $\rightarrow$ all math computed server-side via `calculate_difference()` |
| LLM timeout or service error | Automatic single-retry $\rightarrow$ fallback to `UNRESOLVED` card on repeated failure |
| Double-click on Approve/Reject | Atomic conditional UPDATE $\rightarrow$ returns HTTP 409 Conflict |
| Unauthorized / Path Traversal | Ground truth path strictly validated to reside within `data/` folder |
| Audit Trail Tampering | ORM-level event listeners prevent UPDATE and DELETE on `AuditLog` |
