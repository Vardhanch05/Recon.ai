# Multi-Source Settlement Reconciler
### Razorpay AI Builder Buildathon — Track 4: AI Finance Controller

An AI-powered settlement reconciliation agent that matches Razorpay settlement files against merchant order ledgers, explains ambiguous discrepancies using LLM reasoning, and requires human approval before posting any journal entries.

---

## What It Does

When Razorpay settles funds to a merchant, the payment arrives as a single NEFT credit covering hundreds of orders, net of MDR fees, GST, and refund deductions. Matching this credit back to individual orders is straightforward for clean records — but ambiguous discrepancies (wrong fee rate applied? partial refund deducted? FX rounding?) currently require manual investigation.

This system:
- **Matches ~80% of records deterministically** in under 1 second (no AI, no cost)
- **Explains the remaining ~14%** using an LLM that must verify its arithmetic via a tool call — not free-text reasoning
- **Honestly flags ~6%** as unresolvable rather than inventing explanations
- **Requires human approval** before any ledger entry is posted — the AI never has final authority

---

## Quick Start

### Prerequisites
- Python 3.11+
- Node.js 18+
- PostgreSQL 14+

### Backend Setup
```bash
cd backend
pip install -r requirements.txt
cp .env.example .env          # Add DATABASE_URL and LLM_API_KEY
python -m alembic upgrade head # Run migrations
uvicorn main:app --reload
```

### Frontend Setup
```bash
cd frontend
npm install
npm run dev
```

### Load Synthetic Data
```bash
# Upload the pre-built synthetic dataset
curl -X POST http://localhost:8000/batches/upload \
  -F "settlement_file=@data/synthetic_batch.csv" \
  -F "ledger_file=@data/ledger.csv"
```

---

## Demo Flow

1. Open `http://localhost:3000`
2. Upload `data/synthetic_batch.csv` + `data/ledger.csv`
3. Click **Run Matching** → 44 of 55 records match automatically (80%)
4. Click **Run AI Reasoning** → 7 exceptions explained, 3 flagged UNRESOLVED
5. Review each reasoning card — expand the math table to verify the arithmetic
6. Click **Approve** on each AI-resolved card
7. View the **Audit Log** — every decision is logged immutably
8. Click **Accuracy Report** — 7/7 explainable + 3/3 unresolvable correctly handled

---

## Architecture

```
React Frontend
     ↓ REST API
FastAPI Backend
  ├── Ingestion Service     (deterministic — CSV → DB)
  ├── Matching Engine       (deterministic — order_id + amount fallback)
  ├── LLM Reasoner          (AI — parallel async, tool-calling only)
  ├── Approval Service      (deterministic — atomic guard, human required)
  └── Audit Logger          (immutable — every event logged)
     ↓
PostgreSQL Database
     ↓
LLM API (OpenAI / Claude)
  └── calculate_difference tool (runs server-side)
```

---

## Key Design Decisions

**Why tool-calling for arithmetic?**
LLMs make arithmetic errors in free text. The `calculate_difference` function runs server-side with deterministic Python math. The LLM selects which fee parameters to test; the function computes the result; the server validates consistency before writing to DB.

**Why not LangGraph?**
The core reasoning step is a single LLM call + single tool call per record. LangGraph adds overhead with no benefit here. Plain LangChain `.batch()` handles parallelism. LangGraph would add value for a multi-hypothesis retry loop — an optional enhancement if time allows.

**Why human approval?**
Nothing posts to the ledger without an accountant clicking Approve. The AI surfaces a hypothesis and shows the math — the human verifies and decides. This is the track's explicit requirement and the right design for financial data.

**Why is confidence derived from math, not the LLM?**
LLM self-reported confidence is unreliable and indefensible. The confidence score is computed from `residual_gap` after the tool call. A score of 0.94 means "the arithmetic closes to within ₹0.03" — a verifiable claim, not an LLM's self-assessment.

---

## Project Structure

```
/
├── backend/
│   ├── main.py          # FastAPI app + routes
│   ├── models.py        # SQLAlchemy models
│   ├── ingestion.py     # CSV parsing + DB insert
│   ├── matching.py      # Deterministic matching engine
│   ├── reasoning.py     # LLM reasoner + validate_card + compute_confidence
│   ├── approval.py      # Approve/reject endpoints
│   ├── audit.py         # Audit log writes
│   └── schemas.py       # Pydantic request/response schemas
├── frontend/
│   └── src/components/
│       ├── UploadPanel.tsx
│       ├── MatchRateSummaryCard.tsx
│       ├── ExceptionList.tsx
│       ├── ReasoningCard.tsx
│       └── AuditLogViewer.tsx
├── data/
│   ├── synthetic_batch.csv   # 55-record synthetic settlement file
│   ├── ledger.csv            # Matching order ledger
│   └── ground_truth.csv      # Hidden answer key (pre-built, independent of reasoner)
├── docs/
│   ├── PRD.md                # Product requirements
│   ├── TRD.md                # Technical requirements
│   ├── technical-design.md   # Architecture + algorithm detail
│   ├── backend-schema.md     # Full DDL
│   ├── api.md                # API reference
│   ├── app-flow.md           # User flow walkthrough
│   ├── ui-ux-brief.md        # Component specs + design rules
│   ├── implementation-plan.md # Build order + time estimates
│   ├── research.md           # Problem validation + prior art
│   └── testing-strategy.md   # Test cases for all critical paths
├── AGENTS.md            # AI assistant context file (read before coding)
├── TESTING.md           # Full testing strategy
├── audit.md             # Audit log reference
├── api.md               # API reference (top-level copy)
├── bugs.md              # Known bugs + watch items
├── task_today.md        # Current session task checklist
└── README.md            # This file
```

---

## Environment Variables

```bash
DATABASE_URL=postgresql://user:pass@localhost:5432/reconciler
LLM_API_KEY=sk-...
LLM_MODEL=gpt-4o                  # or claude-3-5-sonnet-20241022
LLM_TIMEOUT_SECONDS=30
TIMESTAMP_TOLERANCE_DEFAULT=2
```

---

## Accuracy Claim

The system is evaluated against a pre-built ground-truth answer key generated *before* the reasoner was built. This prevents circular evaluation ("the explanation sounds plausible" is not accuracy).

Run the accuracy report after a full pipeline pass:
```bash
curl "http://localhost:8000/batches/{batch_id}/accuracy-report?ground_truth_path=data/ground_truth.csv"
```

Expected result on the synthetic dataset:
- 7 of 7 explainable discrepancies correctly categorized
- 3 of 3 unresolvable records correctly flagged UNRESOLVED
- Overall: 10 of 10 non-trivial records handled correctly

---

## Track 4 Compliance

| Requirement | How Satisfied |
|---|---|
| 50+ record batch | 55-record synthetic dataset |
| Match rate reported | MatchRateSummaryCard: 80% / 14% / 6% breakdown |
| Exceptions listed honestly | UNRESOLVED cards shown with attempted hypotheses |
| Not cherry-picked | Accuracy report runs against full batch, not selected records |
| Throughput measured | `throughput_ms` in summary response |
| Human-in-the-loop | No ledger posting without explicit Approve click |
