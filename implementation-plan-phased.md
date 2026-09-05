# Implementation Plan — Multi-Source Settlement Reconciler

Structured for building with Antigravity, tracked via `handoff.md` (session-to-session continuity) and `task_today.md` (daily scoped checklist). You type every line yourself — Antigravity/I explain, you implement, we verify.

---

## How `handoff.md` and `task_today.md` should work together

**`task_today.md`** — rewritten at the start of each work session. Pulled from whichever phase you're in below. Should contain: today's 2–5 concrete tasks, which files they touch, and what "done" looks like for each (a passing test, a working curl call, a rendered component — not "worked on X").

**`handoff.md`** — rewritten at the *end* of each session, before you close Antigravity. This is the memory bridge between sessions, since Antigravity won't remember yesterday's context on its own. It should always contain:
- What was actually completed today (file-level, not phase-level)
- Any decision made that isn't yet reflected in the docs (so it doesn't get silently reverted next session)
- What's broken/half-done right now, explicitly — don't let "in progress" state look finished
- The next task_today.md draft

Treat `handoff.md` as the single most important file in the repo for a multi-session AI-assisted build. Every session should start by reading it, not by re-explaining context to Antigravity from memory.

---

## Phase 0 — Resolve Known Doc Bugs Before Writing Any Code

Every item below was caught in review and would otherwise get implemented literally. Fixing docs first is cheaper than fixing code + tests + docs later.

| Task | File(s) | Done when |
|---|---|---|
| Decide: does `/approve` accept `exception_unresolved` cards, or only `matched_ai_resolved`? (Recommendation from review: restrict to `matched_ai_resolved` only — see rationale in prior review thread) | Decision only, then propagate | Written down once, not re-litigated per file |
| Replace all `status='pending'` / inconsistent `status='exception_unresolved'` guards with the decided clause | `api.md`, `technical-design.md`, `TRD.md`, `AGENTS.md`, `HLD_diagram.png` (relabel or add correction note) | Grep for `'pending'` across all docs returns zero hits |
| Fix `app-flow.md` state diagram — two valid pre-action states, remove `pending`/`journal_posted`/`manual_handling` | `app-flow.md` | Diagram only uses real ENUM values |
| Fix `reasoning_cards` column type swap — `calculation_breakdown` = JSONB, `confidence_score` = DECIMAL(3,2) | `backend-schema.md`, schema diagram | Types match the LLD §3.4 table |
| Fix LLD §5.3 worked example (`965.80` → `954.60`) | `track4-reconciler-lld.md` | Arithmetic in the example checks out |
| Add `amount_match` to `routing_reason` wherever still missing (confirm `AGENTS.md` got it) | `AGENTS.md` and any doc not yet checked | Grep confirms 6 values present everywhere |
| Resolve UNRESOLVED-card approve/reject UI contradiction (Finding 29) — hide Approve, keep Reject, per the decision above | `ui-ux-brief.md` | One stated behavior, matches API guard |
| Log all of the above as closed items in `bugs.md` | `bugs.md` | Each has a BUG-### entry with resolution note |

**Output of this phase:** a `handoff.md` stating "docs are now internally consistent as of [date], implementation starts clean." This is your reference point if anything drifts later.

---

## Phase 1 — Repo & Environment Skeleton

- Initialize repo structure matching (corrected) `README.md`.
- Postgres running locally (Docker Compose recommended — one command, no local install drift).
- Python env + FastAPI skeleton (`uvicorn main:app --reload` returns a health check).
- React app skeleton (Vite, not CRA, for faster iteration) — one placeholder route confirms the dev server runs.
- `.env.example` committed; real `.env` gitignored — you'll need an LLM API key here.

**Done when:** `docker compose up` gives you a running Postgres, `uvicorn` serves a `/health` endpoint, `npm run dev` renders a blank page. Nothing functional yet — this phase is just "does the toolchain work."

---

## Phase 2 — Database Schema + Ingestion Service

This is first because everything else depends on it, and it's the lowest-risk component — pure DDL and CSV parsing, no AI involved.

- Write migration files for all 6 tables from the corrected `backend-schema.md` (`batches`, `settlement_records`, `order_ledger`, `reconciliation_results`, `reasoning_cards`, `exception_candidates`, `audit_log`) — apply every constraint from the schema diagram: FKs, the two `UNIQUE` constraints, the `NOT NULL` on `settlement_record_id`.
- Build `POST /batches/upload`: accepts two CSVs, parses, validates, writes rows, logs malformed rows to `audit_log` as `ingestion_error`, increments `batches.ingestion_error_count`.
- Manually verify: upload a CSV with one deliberately malformed row → confirm it's skipped, logged, and counted — not silently dropped.

**Done when:** you can upload real (even hand-written, 5-row) CSVs and query the DB directly to see correctly normalized rows, with a malformed row correctly routed to the audit log instead of crashing ingestion.

---

## Phase 3 — Synthetic Dataset (build in parallel with Phase 4)

- Write a generator script producing 50–60 records at the documented 80/14/6 split.
- Explicitly construct each of the ~7 "explainable" causes (domestic MDR, international MDR, GST-on-fee, partial refund, flat surcharge, one combined-cause) and the ~3 unresolvable ones.
- Write the hidden ground-truth answer key CSV (`true_cause`, `true_category`) — keep it out of the files Antigravity/the LLM ever sees during reasoning, only used later by the accuracy script.

**Done when:** you have `settlement.csv`, `ledger.csv`, and a separate `ground_truth.csv` that isn't referenced anywhere in the ingestion or reasoning code paths.

---

## Phase 4 — Deterministic Matching Engine

The highest-value component to get right first — this alone gets you a working 80% demo before any LLM code exists.

- Implement the corrected §4.1 algorithm: order_id path trusts the match unconditionally when `fee_deducted` is null, uses fee-adjusted amount as a sanity flag (not a gate) when present; fallback path requires both `fee_deducted` and amount-within-tolerance.
- Implement `routing_reason` tagging for every outcome, success and exception.
- Implement `exception_candidates` writes for the `ambiguous_multiple` case (per the schema's join table, not a single FK).
- Unit tests: order_id match with/without fee_deducted, fallback match, timestamp boundary (exactly at tolerance, one second over), ambiguous multiple candidates, currency mismatch, no match at all.

**Done when:** running the matching engine against your Phase 3 dataset produces close to the designed 80% deterministic match rate, and every exception row has a populated `routing_reason`.

---

## Phase 5 — LLM Reasoner + Tool-Calling (highest risk — start early, don't leave for later)

- Implement `calculate_difference()` exactly per the corrected 7-parameter signature.
- Implement `compute_confidence()` — copy the exact formula, don't approximate it.
- Build the context-object construction per §5.1, including `payment_method` and the `candidate_orders` array form for ambiguous cases.
- Wire the LLM call with forced tool-calling (function-calling mode, not free-text).
- Implement the retry-once-then-UNRESOLVED behavior for the case where the LLM skips the tool call (this was WATCH-003 in your bugs doc).
- Implement `validate_card()` using the corrected `computed_status`-derived check.
- Use LangChain's `.batch()` (not LangGraph) to run exceptions concurrently.

**Done when:** running the reasoner against your Phase 3 dataset's ~7 explainable exceptions produces correct hypotheses with `residual_gap ≈ 0`, and the ~3 unresolvable ones correctly come back `UNRESOLVED` — checked by eye first, formally in Phase 9.

---

## Phase 6 — API Layer

- `POST /batches/{id}/run-matching` (sync)
- `POST /batches/{id}/run-reasoning` (async, returns job_id, frontend polls `/summary`)
- `GET /batches/{id}/summary`, `GET /batches/{id}/exceptions` (paginated)
- `GET /batches/{id}/accuracy-report`
- `GET /batches/{id}/audit-log` (filterable)

**Done when:** you can drive the entire pipeline — upload, match, reason, summarize — via `curl` or Postman, no UI required yet.

---

## Phase 7 — Human Approval + Audit Trail

- `POST /reconciliation/{id}/approve` and `/reject` with the corrected atomic guard from Phase 0's decision.
- Journal posting logic on approve.
- Every event type write to `audit_log`, immutable, from ingestion through journal posting.

**Done when:** approving a card actually changes its status exactly once even under a deliberate double-click test (open two tabs, click both fast), and the audit log shows a complete, ordered trail for one record end-to-end.

---

## Phase 8 — Dashboard UI

Build in this order, each one testable against the live API from Phase 6/7 before moving to the next:
1. `UploadPanel` → confirms Phase 2 works from the browser
2. `MatchRateSummaryCard` → confirms Phase 4/6 numbers render correctly
3. `ExceptionList` + `ReasoningCard` (with the expandable math table, not just prose) → confirms Phase 5 output is legible
4. `ApproveRejectButtons` → confirms Phase 7, including the UNRESOLVED-card button behavior decided in Phase 0
5. `AuditLogViewer` → last, since it's the least demo-critical piece

**Done when:** you can run the entire pipeline start to finish from the browser with no manual API calls.

---

## Phase 9 — Testing & Accuracy Verification

- Run the full test suite, including the timestamp-boundary and tool-call-skip tests flagged in review.
- Run the accuracy report against the hidden ground-truth key — this is your actual "7 of 7 correctly categorized" claim, not an eyeball check.
- Fix anything the confusion matrix reveals before moving on.

**Done when:** the accuracy report runs end-to-end and produces a number you'd be comfortable showing a judge cold.

---

## Phase 10 — Demo Prep

- Pre-cache a known-good reasoning batch as the WATCH-004 live-demo fallback (LLM latency risk).
- Confirm the `known_fee_schedule` file is visibly loaded somewhere in the demo flow, not just hardcoded invisibly.
- Do one full dry run of the pitch: upload → match → reason → approve → audit log → accuracy report, timed.

---

## Suggested `task_today.md` scoping

Don't put a whole phase in one day's file. A reasonable single-day slice is one row of one phase's table, or one sub-bullet of Phase 4/5/8. If a task_today.md item doesn't have an obvious "done when," it's scoped too big — split it before starting.
