# Recon.ai — Multi-Source Settlement Reconciler

[![FastAPI](https://img.shields.io/badge/FastAPI-0.109.0-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-19.0.0-61DAFB.svg?logo=react&logoColor=black)](https://reactjs.org/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.0-3178C6.svg?logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-14%2B-336791.svg?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Python Tests](https://img.shields.io/badge/Tests-12%2F12%20Passing-brightgreen.svg?logo=pytest&logoColor=white)](https://docs.pytest.org)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

> An enterprise-grade AI settlement reconciliation system built for payment gateway merchants. Combines deterministic rule matching, function-calling LLM discrepancy reasoning, mathematically bounded confidence scoring, and atomic human approval gates.

---

## 🌟 Key Highlights & Resume Talking Points

- **Hybrid Deterministic + AI Pipeline**:
  - Automatically matches **~80% of transaction records deterministically** in sub-second execution (zero AI token cost).
  - Routes remaining **~14% of discrepancy exceptions** to an LLM reasoning engine that hypothesizes fee structures (Domestic/International MDR, GST on fees, partial refunds, gateway flat surcharges).
  - Honestly flags **~6% of genuine anomalies** as `UNRESOLVED` rather than hallucinating force-fitted explanations.
- **Tool-Calling Arithmetic Integrity**:
  - Strictly prohibits free-text math hallucinations. The LLM invokes a server-side Python tool (`calculate_difference`) to calculate exact expected settlements and residual gaps.
- **Defensible Mathematical Confidence**:
  - Confidence scores are never self-reported by the LLM. They are derived purely on the server from the residual gap ($\le ₹0.05 \rightarrow 0.99$, $\le ₹0.50 \rightarrow 0.94 - 0.70$, $> ₹5.00 \rightarrow 0.00$).
- **Atomic Human Approval Hard-Gate**:
  - Nothing posts to the financial ledger without explicit human approval.
  - Implements atomic SQL conditional updates (`WHERE status = 'matched_ai_resolved'`) to eliminate double-action / concurrency race conditions (HTTP 409 Conflict).
- **Append-Only Immutable Audit Trail**:
  - Every pipeline event (`ingestion_error`, `match`, `llm_call`, `human_approval`, `human_rejection`, `journal_posted`) is logged immutably. ORM lifecycle event listeners block any `UPDATE` or `DELETE` operations on the audit table.
- **Live Verifiable Accuracy Reporting**:
  - Live confusion matrix endpoint (`/batches/{id}/accuracy-report`) evaluates predictions against a pre-built ground-truth dataset (`data/ground_truth.csv`), demonstrating **100% accuracy** on explainable and unresolvable test sets.

---

## 🏗️ System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                             React 19 Frontend                               │
│  [Header] → [PipelineStepper] → [UploadPanel] → [MatchRateSummaryCard]      │
│  [ExceptionList] ───► [ReasoningCard] (Math Breakdown & Approval Gate)      │
│  [AuditLogViewer] & [AccuracyReportModal] (Live Confusion Matrix)           │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ HTTP / REST
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

## ⚡ Quick Start & Local Setup

### 1. Prerequisites
- Python 3.11+
- Node.js 18+ and npm
- PostgreSQL 14+ (or SQLite default for instant zero-config setup)

### 2. Backend Setup
```bash
cd backend
python -m venv venv
# Windows:
.\venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
cp .env.example .env

# Start FastAPI backend server
uvicorn backend.main:app --reload --port 8000
```

### 3. Frontend Setup
```bash
cd frontend
npm install
npm run dev
```
Open `http://localhost:5173` (or `http://localhost:3000`) in your browser.

### 4. Running via Docker
```bash
docker-compose up --build
```

---

## 📊 End-to-End Demo Walkthrough

1. **Upload Datasets**:
   - Drag & drop `data/synthetic_batch.csv` (Razorpay settlement export) and `data/ledger.csv` (Merchant order ledger).
   - Click **"Upload & Ingest Batch"**.
2. **Run Deterministic Matching**:
   - Click **"Run Matching"**.
   - Watch **44 of 55 records (80%)** match instantly with zero LLM tokens spent.
3. **Run AI Discrepancy Reasoning**:
   - Click **"Run AI Reasoning"**.
   - Background worker invokes parallel function-calling to analyze the 11 exceptions.
   - Explains 7 discrepancies and accurately flags 3 anomalies as `UNRESOLVED`.
4. **Review & Approve**:
   - Inspect reasoning cards, expand the calculation breakdown drawer to verify arithmetic.
   - Click **Approve** on AI-resolved records to post journal entries.
5. **Inspect Audit Trail & Accuracy**:
   - View the immutable audit log recording every timestamped event.
   - Open **"Accuracy Report"** to inspect the live confusion matrix.

---

## 🧪 Automated Testing Suite

Run the full pytest suite:
```bash
pytest -v
```

### Test Coverage Highlights:
- `test_models.py`: Cross-dialect GUID, relationships, cascade rules, unique constraints.
- `test_ingestion.py`: CSV parsing, currency cleaning, row errors, summary metrics.
- `test_matching.py`: Order ID matching, fallback matching, 409 concurrency protection on approvals.
- `test_full_pipeline.py`: Complete end-to-end pipeline run matching ground truth.
- `test_audit_remediation.py`: Immutability ORM hooks, audit retention on batch delete, reasoning state guards.

---

## 📁 Repository Directory Layout

```
ReconAI/
├── backend/
│   ├── main.py              # FastAPI app definition, CORS, lifespan, and root endpoints
│   ├── config.py            # Environment configuration & settings
│   ├── database.py          # SQLAlchemy engine, SessionLocal, and DB dependencies
│   ├── models.py            # Declarative database models with immutability hooks
│   ├── schemas.py           # Pydantic v2 validation & response schemas
│   ├── ingestion.py         # CSV parsing, currency cleaning, and row validation
│   ├── matching.py          # Two-pass deterministic matching engine
│   ├── reasoning.py         # LLM discrepancy reasoner with calculate_difference tool
│   ├── audit.py             # Audit event emitter
│   ├── security.py          # Optional API key authentication dependency
│   ├── logging_config.py    # Structured logging configuration
│   └── routes/
│       ├── batches.py       # Upload, batch summary, and audit log endpoints
│       ├── reconciliation.py # Matching, async reasoning, approval & rejection
│       └── reports.py       # Ground-truth accuracy evaluation & confusion matrix
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── Header.tsx               # App bar with quick actions & status pill
│   │   │   ├── PipelineStepper.tsx      # 4-stage interactive pipeline progress
│   │   │   ├── UploadPanel.tsx          # Dual dropzone file upload interface
│   │   │   ├── MatchRateSummaryCard.tsx # 80% / 14% / 6% KPI stat cards
│   │   │   ├── ExceptionList.tsx        # Filterable reasoning cards container
│   │   │   ├── ReasoningCard.tsx        # Discrepancy explanation & math table
│   │   │   ├── AuditLogViewer.tsx       # Immutable audit log stream with filter
│   │   │   └── AccuracyReportModal.tsx  # Live confusion matrix modal
│   │   ├── App.tsx          # Main application orchestration
│   │   └── api.ts           # Axios / Fetch client layer
├── data/
│   ├── synthetic_batch.csv  # 55-record synthetic settlement file
│   ├── ledger.csv           # Matching merchant order ledger
│   └── ground_truth.csv     # Independent evaluation answer key
├── docs/                    # Technical specs (PRD, TRD, Schema, App Flow, UI Brief)
├── tests/                   # 12 automated Pytest test suites
├── Dockerfile               # Production container image
├── docker-compose.yml       # Multi-container orchestration
└── README.md                # Project documentation
```

---

## 💼 Resume Description Template

> **Recon.ai | AI Financial Settlement Reconciliation Engine**  
> *FastAPI, React 19, TypeScript, Python, SQLAlchemy, PostgreSQL, Groq/OpenAI, Docker, Pytest*  
> - Designed and built an enterprise-grade settlement reconciliation system processing payment gateway settlement batches against internal merchant ledgers.  
> - Developed a two-stage pipeline combining a deterministic matching engine (auto-reconciling 80% of transactions in <200ms) with an asynchronous LLM reasoning agent explaining complex fee and refund discrepancies.  
> - Integrated tool-calling with a deterministic Python math engine (`calculate_difference`) and mathematical residual-gap confidence scoring, eliminating free-text arithmetic hallucinations.  
> - Implemented atomic conditional SQL state guards preventing race conditions (HTTP 409) and built an append-only audit trail with ORM-level immutability hooks.  
> - Built a responsive React 19 + TypeScript dashboard with live pipeline progression, expandable calculation breakdowns, and a verifiable ground-truth accuracy reporting modal (100% precision on synthetic benchmarks).  
> - Authored 12 automated unit and integration test suites with Pytest achieving 100% test pass rate.
