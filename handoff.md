# handoff.md
## Session Handoff — Settlement Reconciler

Use this file when switching sessions or tools. It captures exactly where you are and what to do next.

---

## Current Status

- Status: ALL PHASES COMPLETE (Phases 1 through 7)
- Automated Test Suite: 6/6 tests passing (`pytest -vv`)
- Frontend: TypeScript compiled cleanly (`npm run build`), running dev server on Vite (`http://localhost:5173`)
- Backend: FastAPI service ready on `http://localhost:8000` with full Swagger docs at `/docs`

---

## What's Been Built

- **Backend Ingestion & Parsing**: [ingestion.py](file:///d:/personal/projects/ReconAI/backend/ingestion.py) for Razorpay settlement + Order ledger CSVs, error counting and validation.
- **Deterministic Match Engine**: [matching.py](file:///d:/personal/projects/ReconAI/backend/matching.py) (order_id primary pass + fee-adjusted amount/timestamp fallback, candidate routing).
- **Discrepancy Reasoner & Math Tool**: [reasoning.py](file:///d:/personal/projects/ReconAI/backend/reasoning.py) (`calculate_difference`, `compute_confidence`, `validate_card`, batch async reasoning).
- **Approval & Audit Workflows**: [reconciliation.py](file:///d:/personal/projects/ReconAI/backend/routes/reconciliation.py) (atomic state guards, 409 double-action prevention, journal posting, audit logging).
- **Accuracy Reporting**: [reports.py](file:///d:/personal/projects/ReconAI/backend/routes/reports.py) (ground truth evaluation & confusion matrix generator).
- **Interactive React Frontend**:
  - [App.tsx](file:///d:/personal/projects/ReconAI/frontend/src/App.tsx)
  - [UploadPanel.tsx](file:///d:/personal/projects/ReconAI/frontend/src/components/UploadPanel.tsx)
  - [PipelineStepper.tsx](file:///d:/personal/projects/ReconAI/frontend/src/components/PipelineStepper.tsx)
  - [MatchRateSummaryCard.tsx](file:///d:/personal/projects/ReconAI/frontend/src/components/MatchRateSummaryCard.tsx)
  - [ExceptionList.tsx](file:///d:/personal/projects/ReconAI/frontend/src/components/ExceptionList.tsx)
  - [ReasoningCard.tsx](file:///d:/personal/projects/ReconAI/frontend/src/components/ReasoningCard.tsx)
  - [AuditLogViewer.tsx](file:///d:/personal/projects/ReconAI/frontend/src/components/AuditLogViewer.tsx)
  - [AccuracyReportModal.tsx](file:///d:/personal/projects/ReconAI/frontend/src/components/AccuracyReportModal.tsx)
- **Synthetic Datasets**: `data/synthetic_batch.csv`, `data/ledger.csv`, `data/ground_truth.csv`.

---

## How to Run & Verify

1. **Start Backend**: `uvicorn backend.main:app --reload --port 8000`
2. **Start Frontend**: `npm run dev` in `frontend/` (accessible at `http://localhost:5173`)
3. **Run All Tests**: `pytest -vv` in project root
