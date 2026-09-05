# tasks.md
## Implementation Task Plan — Settlement Reconciler
### 3 tasks per day = 3 GitHub commits per day

Each task is designed to be:
- Completable in 1–3 hours
- A self-contained, working commit (not broken mid-feature)
- Buildable by typing code manually with Antigravity

---

## DAY 1 — Project Scaffold + Database

### Task 1.1 — Project structure + environment setup
**Commit message:** `chore: init project structure, virtualenv, dependencies`

What you build:
- Create folder structure: `backend/`, `frontend/`, `data/`, `tests/`
- Create `backend/requirements.txt` with: fastapi, uvicorn, sqlalchemy, psycopg2-binary, python-dotenv, alembic, pydantic, langchain, openai, python-multipart
- Create `backend/.env.example` with DATABASE_URL, LLM_API_KEY, LLM_MODEL, LLM_TIMEOUT_SECONDS
- Create `backend/main.py` — bare FastAPI app with a `GET /health` endpoint
- Run it: `uvicorn main:app --reload` → confirm `{"status": "ok"}`

Codebase after this task:
```
backend/
├── main.py          ← NEW: FastAPI app skeleton
├── requirements.txt ← NEW: all dependencies listed
└── .env.example     ← NEW: env var template
```

---

### Task 1.2 — Database models (SQLAlchemy)
**Commit message:** `feat: add SQLAlchemy models for all 7 tables`

What you build:
- Create `backend/models.py`
- Define all enums: `BatchStatus`, `ReconciliationStatus`, `RoutingReason`, `ResolutionSource`, `AuditEventType`
- Define all 7 models: `Batch`, `SettlementRecord`, `OrderLedger`, `ReconciliationResult`, `ExceptionCandidate`, `ReasoningCard`, `AuditLog`
- Include all constraints: UNIQUE(batch_id, gateway_txn_id), UNIQUE(batch_id, settlement_record_id), NOT NULL on settlement_record_id
- Create `backend/database.py` — SQLAlchemy engine + session setup, reads DATABASE_URL from env

Codebase after this task:
```
backend/
├── main.py
├── models.py        ← NEW: all 7 table models + enums
├── database.py      ← NEW: DB engine + get_db() session dependency
├── requirements.txt
└── .env.example
```

---

### Task 1.3 — Alembic migrations + DB creation
**Commit message:** `feat: alembic migrations, create all tables in postgres`

What you build:
- Run `alembic init alembic` inside `backend/`
- Edit `alembic/env.py` to import your models and use the DATABASE_URL
- Create initial migration: `alembic revision --autogenerate -m "initial schema"`
- Review the generated migration file — verify all tables, enums, indexes, constraints are present
- Run migration: `alembic upgrade head`
- Open psql and confirm all 7 tables exist with correct columns

Codebase after this task:
```
backend/
├── alembic/
│   ├── env.py           ← MODIFIED: points to your models
│   └── versions/
│       └── xxxx_initial_schema.py  ← NEW: auto-generated migration
├── alembic.ini          ← NEW: alembic config
├── main.py
├── models.py
├── database.py
├── requirements.txt
└── .env.example
```

---

## DAY 2 — Ingestion Service

### Task 2.1 — Pydantic schemas
**Commit message:** `feat: add pydantic request/response schemas`

What you build:
- Create `backend/schemas.py`
- Define: `BatchResponse`, `SettlementRecordIn`, `OrderLedgerIn`, `UploadResponse`, `SummaryResponse`
- `SummaryResponse` must include all fields from the API spec: batch_id, status, total_records, matched_deterministic_count, matched_ai_resolved_count, unresolved_count, ingestion_error_count, match_rate_deterministic_pct, match_rate_ai_resolved_pct, throughput_ms

Codebase after this task:
```
backend/
├── schemas.py       ← NEW: all Pydantic in/out models
├── ...
```

---

### Task 2.2 — CSV parsing + ingestion logic
**Commit message:** `feat: ingestion service — parse settlement + ledger CSVs`

What you build:
- Create `backend/ingestion.py`
- Function `parse_settlement_csv(file) -> tuple[list[dict], int]` — returns parsed rows + error count
- Function `parse_ledger_csv(file) -> tuple[list[dict], int]`
- Validate each row: required fields present, amounts are valid decimals, timestamps parseable
- On malformed row: log to audit_log as `ingestion_error`, skip, increment error count
- Function `ingest_batch(db, settlement_rows, ledger_rows, batch_id)` — writes to DB

Codebase after this task:
```
backend/
├── ingestion.py     ← NEW: CSV parsing + DB insert logic
├── ...
```

---

### Task 2.3 — Upload endpoint
**Commit message:** `feat: POST /batches/upload endpoint`

What you build:
- In `backend/main.py`, add `POST /batches/upload`
- Accept multipart: `settlement_file`, `ledger_file`, optional `timestamp_tolerance_seconds`
- Create a `Batch` row in DB
- Call ingestion functions from Task 2.2
- Return `UploadResponse` with batch_id, total_records, ingestion_error_count, status
- Handle duplicate batch: check if gateway_txn_ids already exist for a batch, return 409

Test it: `curl -X POST /batches/upload -F settlement_file=@data/synthetic_batch.csv -F ledger_file=@data/ledger.csv`

Codebase after this task:
```
backend/
├── main.py          ← MODIFIED: added /batches/upload route
├── ingestion.py     ← used by the route
├── ...
```

---

## DAY 3 — Deterministic Matching Engine

### Task 3.1 — Matching logic (order_id path)
**Commit message:** `feat: matching engine — primary order_id match path`

What you build:
- Create `backend/matching.py`
- Function `match_by_order_id(db, settlement_record) -> tuple[OrderLedger | None, str]`
  - Null-safe order_id query
  - If exactly one candidate: run optional fee sanity check if fee_deducted present
  - Returns (candidate, routing_reason) or (None, reason)
- Write `ReconciliationResult` rows for matched records
- Log each match to audit_log

Codebase after this task:
```
backend/
├── matching.py      ← NEW: order_id match path
├── ...
```

---

### Task 3.2 — Matching logic (fallback path + exception routing)
**Commit message:** `feat: matching engine — fallback path + exception routing`

What you build:
- Add to `backend/matching.py`:
  - `match_by_amount_and_time(db, settlement_record, tolerance_secs)` — fallback path
  - Only runs if fee_deducted IS NOT NULL
  - Route to exception with correct `routing_reason` tag
  - For `ambiguous_multiple`: insert all candidates into `exception_candidates` table
- Function `run_matching_pass(db, batch_id)` — orchestrates the full pass for a batch
- Idempotent: use upsert pattern on UNIQUE(batch_id, settlement_record_id)
- Update `batches.status` → `matching_complete`, compute `match_rate_deterministic`

Codebase after this task:
```
backend/
├── matching.py      ← MODIFIED: fallback path + full orchestration added
├── ...
```

---

### Task 3.3 — Run-matching endpoint + summary endpoint (partial)
**Commit message:** `feat: POST /run-matching and GET /summary endpoints`

What you build:
- In `main.py`: add `POST /batches/{batch_id}/run-matching`
  - Calls `run_matching_pass()`
  - Returns match counts + status
- In `main.py`: add `GET /batches/{batch_id}/summary`
  - Returns `SummaryResponse` from the `batches` table
  - Handle null fields correctly (not yet reasoning_complete — some fields will be null)

Test it: upload CSVs → run matching → check summary shows ~80% matched

Codebase after this task:
```
backend/
├── main.py          ← MODIFIED: two new routes
├── matching.py      ← used by run-matching route
├── ...
```

---

## DAY 4 — Synthetic Dataset + Confidence Logic

### Task 4.1 — Build synthetic dataset
**Commit message:** `data: add synthetic settlement batch + ledger + ground truth`

What you build:
- Create `data/synthetic_batch.csv` — 55 records:
  - 40 with clean order_ids and matching amounts (after MDR)
  - 7 with discrepancies: domestic MDR, intl MDR, GST-on-fee, partial refund, flat surcharge, 1 combined
  - 3 with large nonsensical gaps (₹200+) — unresolvable
- Create `data/ledger.csv` — matching order ledger
- Create `data/ground_truth.csv` — gateway_txn_id, true_category, true_cause for 10 non-trivial records
- Run the matching engine against the data — verify ~40 records auto-match

Codebase after this task:
```
data/
├── synthetic_batch.csv   ← NEW
├── ledger.csv            ← NEW
└── ground_truth.csv      ← NEW (keep separate from reasoner logic)
```

---

### Task 4.2 — compute_confidence + validate_card
**Commit message:** `feat: compute_confidence and validate_card functions`

What you build:
- Create `backend/reasoning.py`
- Implement `compute_confidence(residual_gap: float) -> tuple[float, str]` — exact formula from AGENTS.md
- Implement `validate_card(card: dict) -> dict` — overrides LLM output using computed_status
- Write unit tests in `tests/unit/test_confidence.py`:
  - Test band boundaries: gap=0.0, gap=0.05, gap=0.50, gap=0.51, gap=5.00, gap=5.01
  - Test negative gap treated as absolute value
  - Test validate_card overrides wrong LLM category
  - Test validate_card preserves correct UNRESOLVED

Codebase after this task:
```
backend/
├── reasoning.py     ← NEW: compute_confidence + validate_card
tests/
└── unit/
    └── test_confidence.py  ← NEW: unit tests
```

---

### Task 4.3 — calculate_difference tool function
**Commit message:** `feat: calculate_difference tool + unit tests`

What you build:
- Add to `backend/reasoning.py`:
  - `calculate_difference(billed_amount, settled_amount, fee_pct=0, gst_on_fee_pct=0, flat_surcharge=0, refund_amount=0, fx_adjustment=0) -> dict`
  - Returns: expected_settlement, actual_settlement, residual_gap
- Add input guard: if `fee_pct < 0.5` and `fee_pct > 0`, log a warning (likely decimal/percentage confusion)
- Write unit tests in `tests/unit/test_calculate_difference.py`:
  - domestic MDR only
  - intl MDR + GST
  - combined cause (MDR + refund + surcharge)
  - negative gap (over-settlement)
  - fee_pct=0.03 warning case

Codebase after this task:
```
backend/
├── reasoning.py     ← MODIFIED: calculate_difference added
tests/
└── unit/
    └── test_calculate_difference.py  ← NEW
```

---

## DAY 5 — LLM Reasoner

### Task 5.1 — LLM context builder
**Commit message:** `feat: LLM context builder for exceptions`

What you build:
- Add to `backend/reasoning.py`:
  - `build_exception_context(db, reconciliation_result) -> dict`
  - Fetches settlement_record + candidate order(s) from DB
  - For single candidate: builds `candidate_order` dict including `payment_method`
  - For `ambiguous_multiple`: fetches all from `exception_candidates`, builds `candidate_orders: [...]`
  - Attaches `known_fee_schedule` from config/env
  - Attaches `routing_reason`

Codebase after this task:
```
backend/
├── reasoning.py     ← MODIFIED: context builder added
```

---

### Task 5.2 — LLM call + tool registration
**Commit message:** `feat: LLM reasoning call with calculate_difference tool`

What you build:
- Add to `backend/reasoning.py`:
  - Register `calculate_difference` as an OpenAI/LangChain function tool
  - `reason_single_exception(context: dict) -> dict` — makes LLM call, handles tool invocation, returns raw card
  - If LLM returns free-text instead of tool call: retry once, then fallback to UNRESOLVED
  - After LLM response: call `validate_card()` before returning
  - Log `llm_call` event to audit_log

Codebase after this task:
```
backend/
├── reasoning.py     ← MODIFIED: LLM call + tool registration
```

---

### Task 5.3 — Async batch reasoning + run-reasoning endpoint
**Commit message:** `feat: POST /run-reasoning async endpoint with parallel processing`

What you build:
- Add to `backend/reasoning.py`:
  - `run_reasoning_pass(db, batch_id)` — fetches all exceptions, runs `reason_single_exception` via LangChain `.batch()` in parallel
  - Writes `reasoning_cards` rows
  - Updates `reconciliation_results` status: `matched_ai_resolved` or `exception_unresolved`
  - Updates `batches.status` → `reasoning_complete`, computes `match_rate_ai_resolved`
- In `main.py`: add `POST /batches/{batch_id}/run-reasoning`
  - Runs as `BackgroundTasks`
  - Returns 202 with job_id immediately
  - Frontend polls `/summary` for completion

Codebase after this task:
```
backend/
├── main.py          ← MODIFIED: /run-reasoning route added
├── reasoning.py     ← MODIFIED: full async batch pass
```

---

## DAY 6 — Approval + Audit

### Task 6.1 — Approve + reject endpoints
**Commit message:** `feat: POST /approve and /reject with atomic guard`

What you build:
- Create `backend/approval.py`
  - `approve_result(db, result_id, reviewed_by) -> ReconciliationResult`
    - Atomic: `UPDATE WHERE id=:id AND status='exception_unresolved'`
    - If rowcount==0: raise 409
    - Write journal entry (update reconciliation_result, log journal_posted)
  - `reject_result(db, result_id, reviewed_by, override_note) -> ReconciliationResult`
    - Same atomic pattern
    - Store override_note in reasoning_cards.human_override_note
- In `main.py`: add both routes, import from approval.py

Codebase after this task:
```
backend/
├── approval.py      ← NEW: approve/reject logic
├── main.py          ← MODIFIED: two new routes
```

---

### Task 6.2 — Audit log endpoint + exceptions endpoint
**Commit message:** `feat: GET /audit-log and GET /exceptions endpoints`

What you build:
- In `main.py`:
  - `GET /batches/{id}/audit-log` — query audit_log with optional event_type + date filters, paginated
  - `GET /batches/{id}/exceptions` — query reconciliation_results + reasoning_cards joined, paginated
- Both return properly shaped response objects from schemas.py
- Verify audit_log has the (batch_id, timestamp) index in use

Codebase after this task:
```
backend/
├── main.py          ← MODIFIED: two new GET routes
├── schemas.py       ← MODIFIED: add ExceptionResponse, AuditLogResponse schemas
```

---

### Task 6.3 — Accuracy report endpoint
**Commit message:** `feat: GET /accuracy-report endpoint`

What you build:
- In `main.py`: add `GET /batches/{id}/accuracy-report?ground_truth_path=...`
- Load ground_truth.csv by path
- Query reasoning_cards.suggested_category for all non-trivial records
- Join on gateway_txn_id
- Return confusion matrix: correct/total for explainable records + UNRESOLVED records
- Test: run full pipeline on synthetic data → hit this endpoint → should show 7/7 + 3/3

Codebase after this task:
```
backend/
├── main.py          ← MODIFIED: accuracy-report route
```

---

## DAY 7 — React Frontend

### Task 7.1 — React project init + UploadPanel
**Commit message:** `feat: React app init, UploadPanel component`

What you build:
- `cd frontend && npx create-react-app . --template typescript` (or Vite)
- Install axios for API calls
- Create `src/components/UploadPanel.tsx`
  - Two file inputs: settlement file + ledger file
  - "Upload & Process" button — disabled until both files selected
  - On submit: POST /batches/upload, store batch_id in state
  - Show error count warning if ingestion_error_count > 0

Codebase after this task:
```
frontend/
├── src/
│   ├── App.tsx              ← MODIFIED: renders UploadPanel
│   └── components/
│       └── UploadPanel.tsx  ← NEW
```

---

### Task 7.2 — MatchRateSummaryCard + Pipeline Stepper
**Commit message:** `feat: MatchRateSummaryCard and PipelineStepper components`

What you build:
- `src/components/MatchRateSummaryCard.tsx`
  - Polls GET /summary every 2s until reasoning_complete
  - Shows 3 stat blocks: deterministic %, AI-resolved %, unresolved %
  - Shows throughput timer
  - Shows "--" for null values (not yet computed)
- `src/components/PipelineStepper.tsx`
  - 4 steps: Upload → Match → AI Reasoning → Complete
  - Driven by batch.status from /summary response
  - "Run Matching" and "Run AI Reasoning" buttons, enabled/disabled by status

Codebase after this task:
```
frontend/src/components/
├── UploadPanel.tsx
├── MatchRateSummaryCard.tsx  ← NEW
└── PipelineStepper.tsx       ← NEW
```

---

### Task 7.3 — ReasoningCard + ExceptionList + AuditLogViewer
**Commit message:** `feat: ReasoningCard, ExceptionList, AuditLogViewer components`

What you build:
- `src/components/ReasoningCard.tsx`
  - hypothesis_text display
  - Expandable math table (billed, fee%, GST%, expected, actual, gap)
  - Confidence badge: green (≥0.70) / amber (0.30–0.69) / red (0.0 UNRESOLVED)
  - Approve/Reject buttons → POST /approve or /reject
  - Handle 409: show toast "Already actioned"
  - After approval: green "Approved" state; after rejection: red "Rejected" state
- `src/components/ExceptionList.tsx` — fetches GET /exceptions, renders list of ReasoningCards
- `src/components/AuditLogViewer.tsx` — fetches GET /audit-log, event_type filter dropdown, table display
- Wire everything into `App.tsx`

Codebase after this task:
```
frontend/src/components/
├── ReasoningCard.tsx    ← NEW
├── ExceptionList.tsx    ← NEW
└── AuditLogViewer.tsx   ← NEW
```

Full app is now end-to-end functional.

---

## Summary

| Day | Tasks | What You Have After |
|---|---|---|
| 1 | Scaffold, Models, Migrations | Bare FastAPI app + all 7 DB tables live in Postgres |
| 2 | Schemas, Ingestion, Upload | Upload CSVs → see rows in DB |
| 3 | Matching engine, endpoints | Upload → match → see 80% auto-matched |
| 4 | Synthetic data, confidence | Real test data + `compute_confidence` + `calculate_difference` tested |
| 5 | LLM reasoner, async endpoint | Full pipeline runs — reasoning cards written to DB |
| 6 | Approve/reject, audit, accuracy | Complete backend API — all 9 endpoints working |
| 7 | React frontend | Full working app — upload → match → reason → approve |

---

## GitHub Commit Hygiene

Each task = one commit. Suggested branch structure:
```
main
├── day-1/scaffold
├── day-1/models
├── day-1/migrations
├── day-2/schemas
...
```

Or commit directly to main with clear messages — your call. The commit messages above are ready to use.
