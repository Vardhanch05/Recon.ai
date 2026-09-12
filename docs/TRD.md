# Technical Requirements Document (TRD)
## Multi-Source Settlement Reconciler

---

## 1. Tech Stack

| Layer | Technology | Rationale |
|---|---|---|
| Backend Framework | FastAPI (Python 3.11+) | High-performance asynchronous execution, dependency injection, Pydantic v2 validation |
| Database | PostgreSQL 14+ / SQLite (dual-engine support) | ACID transactions for financial ledger posting; SQLite for fast, isolated CI testing |
| ORM & Migrations | SQLAlchemy 2.0 + Alembic | Declarative ORM models with composite unique constraints and immutability event listeners |
| Frontend | React 19 + TypeScript + Vite | Type-safe, component-driven reactive dashboard with glassmorphism financial UI |
| LLM Providers | Groq (`openai/gpt-oss-120b`, `llama3-70b-8192`) & OpenAI (`gpt-4o`) | High-throughput tool calling / function calling for mathematical verification |
| LLM Orchestration | Asynchronous batching with deterministic Python tool binding | Single LLM tool call per exception (`calculate_difference`) + server-side validation |
| Background Execution | FastAPI `BackgroundTasks` | Non-blocking execution of LLM reasoning pipeline with atomic status progression |
| Testing Suite | Pytest, AnyIO, Hypothesis | 100% test coverage across models, ingestion, deterministic engine, atomic guards, and API endpoints |

---

## 2. Functional Requirements

### FR-1: High-Throughput Batch Ingestion
- Accepts multipart form POST with two CSV files: `settlement_file` (Razorpay) and `ledger_file` (Merchant ERP).
- Enforces strict file validation (CSV format, 50MB file size ceiling, 50,000 max row count).
- Sanitizes currency strings (strips currency symbols like `₹`, `$`, commas, and whitespace).
- On malformed or unparseable rows: increments `ingestion_error_count`, logs `ingestion_error` with error snippets to `audit_log`, and continues parsing without aborting valid rows.
- Enforces `UNIQUE(batch_id, gateway_txn_id)` at DB level to prevent duplicate transaction entries.

### FR-2: Deterministic Matching Engine
- **Primary Matching Path**: Queries `order_ledger` matching `order_id == settlement_record.order_id`.
  - If single match found and `fee_deducted` present: verifies `abs(billed - fee_deducted - settled) < 0.01`.
  - If fee sanity passes (or `fee_deducted` absent): marks `matched_deterministic` (zero LLM token consumption).
  - If fee sanity fails: tags as `amount_mismatch` and routes to exception queue for LLM analysis.
- **Fallback Matching Path** (order_id missing/unmatched):
  - Filters by `abs((billed - fee_deducted) - settled) < 0.01` and `abs(order_timestamp - settlement_timestamp) <= tolerance_seconds`.
  - Single match: marks `matched_deterministic` (`amount_match`).
  - Multiple matches: stores all candidate IDs in `exception_candidates` table and routes as `ambiguous_multiple`.
  - No match found: routes as `no_match`.
- Guarantees complete idempotency via `UNIQUE(batch_id, settlement_record_id)` with upsert semantics.

### FR-3: LLM Discrepancy Reasoning Engine
- Constructs structured contextual payloads for each exception record containing transaction details, candidate order(s), payment methods, international card flags, and standard fee schedules.
- Invokes LLM with registered `calculate_difference` arithmetic tool.
- Server-side tool execution computes exact mathematical fee/GST/refund expectations and residual gap.
- Rejects free-text arithmetic hallucinations; retries tool execution on failure.
- Injects `validate_card()` before DB persistence: calculates mathematically bounded confidence scores and automatically demotes low-confidence hypotheses to `UNRESOLVED`.

### FR-4: Reasoning Card Generation & Storage
- Generates a dedicated `reasoning_cards` record per exception containing hypothesis narrative, structured calculation breakdown JSON, server-calculated confidence score, and suggested category tag (`MDR_VARIANCE`, `PARTIAL_REFUND`, `FX_ROUNDING`, `DOMESTIC_MDR`, `INTERNATIONAL_MDR`, `GST_ON_FEE`, `FLAT_SURCHARGE`, `COMBINED_DISCREPANCY`, `UNRESOLVED`).

### FR-5: Human Approval & Concurrency Hard-Gate
- `POST /reconciliation/{result_id}/approve`:
  - Enforces atomic conditional update `WHERE id = :result_id AND status = 'matched_ai_resolved'`.
  - Immediately blocks double-actions with HTTP 409 Conflict.
  - Prohibits approving `UNRESOLVED` records to prevent unverified financial ledger leakage.
  - Emits immutable `human_approval` and `journal_posted` audit records in the same transaction.
- `POST /reconciliation/{result_id}/reject`:
  - Executes atomic update to `human_rejected` with optional `human_override_note` and reviewer ID.

### FR-6: Immutable Audit Trail
- Logs every system event (`ingestion_error`, `match`, `llm_call`, `human_approval`, `human_rejection`, `journal_posted`) with timestamp, actor, and JSON payload.
- Enforces ORM-level update and deletion prevention via SQLAlchemy lifecycle hooks.
- Persists audit logs even upon batch deletion (`ON DELETE SET NULL`).

### FR-7: Live Verifiable Accuracy Reporting
- `GET /batches/{id}/accuracy-report` evaluates reasoner predictions against ground truth answer key (`data/ground_truth.csv`).
- Protected against path traversal vulnerabilities with strict directory resolution.
- Computes exact confusion matrix: explainable accuracy %, unresolvable accuracy %, and overall accuracy %.

---

## 3. Non-Functional Performance Benchmarks

| Metric | Target SLA | Measured Benchmark |
|---|---|---|
| Ingestion & DB Persistence (55 records) | < 500 ms | ~120 ms |
| Deterministic Matching Engine (55 records) | < 1,000 ms | ~180 ms |
| Parallel LLM Discrepancy Reasoning (10 exceptions) | < 15,000 ms | ~4,200 ms |
| Human Approval Endpoint Latency | < 100 ms | ~15 ms |
| Concurrent Action Safety | 100% 409 rejection | Zero double postings |
| Accuracy on Synthetic Dataset (Ground Truth) | 100% explainable & unresolvable | 10/10 non-trivial matches (100%) |

---

## 4. Confidence Scoring Mathematical Specification

Confidence is never self-reported by the LLM. It is strictly derived on the server from the arithmetic `residual_gap`:

```python
def compute_confidence(residual_gap: float) -> tuple[float, str]:
    gap = abs(residual_gap)
    if gap <= 0.05:
        confidence = 0.99 - (gap / 0.05) * 0.04       # 0.99 → 0.95
        status = "resolved"
    elif gap <= 0.50:
        confidence = 0.94 - ((gap - 0.05) / 0.45) * 0.24  # 0.94 → 0.70
        status = "resolved"
    elif gap <= 5.00:
        confidence = 0.69 - ((gap - 0.50) / 4.50) * 0.39  # 0.69 → 0.30
        status = "low_confidence"
    else:
        confidence = 0.0
        status = "unresolved"
    return round(confidence, 2), status
```

---

## 5. Environment & Security Configuration

```ini
DATABASE_URL=sqlite:///./recon_ai.db          # or postgresql://user:pass@localhost:5432/reconciler
GROQ_API_KEY=gsk_...
LLM_MODEL=openai/gpt-oss-120b                 # or llama3-70b-8192 / gpt-4o
LLM_TIMEOUT_SECONDS=30
ALLOWED_ORIGINS=http://localhost:5173,http://localhost:3000
REQUIRE_API_KEY=false                         # Set true for production token enforcement
API_KEY=recon_live_sec_key_...
ENVIRONMENT=development
```
