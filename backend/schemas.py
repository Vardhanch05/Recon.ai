from datetime import datetime
from typing import Optional, List, Any, Dict
from pydantic import BaseModel, Field
import uuid

# ─────────────────────────────────────────────
# INGESTION & BATCH SCHEMAS
# ─────────────────────────────────────────────

class SettlementRecordIn(BaseModel):
    gateway_txn_id: str
    order_id: Optional[str] = None
    settled_amount: float
    settlement_timestamp: datetime
    fee_deducted: Optional[float] = None
    currency: str = "INR"
    raw_row_json: Dict[str, Any]


class OrderLedgerIn(BaseModel):
    order_id: str
    billed_amount: float
    order_timestamp: datetime
    refund_amount: Optional[float] = None
    is_international: bool = False
    payment_method: Optional[str] = None
    raw_row_json: Dict[str, Any]


class UploadResponse(BaseModel):
    batch_id: uuid.UUID
    total_records: int
    ingestion_error_count: int
    status: str


class BatchSummaryResponse(BaseModel):
    batch_id: uuid.UUID
    status: str
    total_records: Optional[int] = 0
    matched_deterministic_count: Optional[int] = 0
    matched_ai_resolved_count: Optional[int] = 0
    unresolved_count: Optional[int] = 0
    ingestion_error_count: Optional[int] = 0
    match_rate_deterministic_pct: Optional[float] = None
    match_rate_ai_resolved_pct: Optional[float] = None
    throughput_ms: Optional[int] = None


class MatchRunResponse(BaseModel):
    batch_id: uuid.UUID
    status: str
    matched_deterministic_count: int
    exception_count: int
    match_rate_deterministic_pct: float


class ReasoningRunResponse(BaseModel):
    batch_id: uuid.UUID
    job_id: uuid.UUID
    exception_count: int
    message: str


# ─────────────────────────────────────────────
# EXCEPTION & REASONING CARD SCHEMAS
# ─────────────────────────────────────────────

class CalculationBreakdown(BaseModel):
    billed_amount: Optional[float] = None
    fee_pct_tested: Optional[float] = None
    gst_on_fee_pct_tested: Optional[float] = None
    flat_surcharge_tested: Optional[float] = None
    refund_amount_tested: Optional[float] = None
    fx_adjustment_tested: Optional[float] = None
    expected_settlement: Optional[float] = None
    actual_settlement: Optional[float] = None
    residual_gap: float
    attempts_tried: Optional[List[str]] = None


class ReasoningCardOut(BaseModel):
    id: uuid.UUID
    hypothesis_text: str
    calculation_breakdown: Dict[str, Any]
    confidence_score: float
    suggested_category: str
    requires_human_review: bool
    human_override_note: Optional[str] = None


class SettlementRecordOut(BaseModel):
    gateway_txn_id: str
    order_id: Optional[str] = None
    settled_amount: float
    settlement_timestamp: datetime
    fee_deducted: Optional[float] = None
    currency: str


class OrderLedgerOut(BaseModel):
    order_id: str
    billed_amount: float
    order_timestamp: datetime
    refund_amount: Optional[float] = None
    is_international: bool
    payment_method: Optional[str] = None


class ExceptionItemOut(BaseModel):
    reconciliation_result_id: uuid.UUID
    settlement_record: SettlementRecordOut
    candidate_orders: Optional[List[OrderLedgerOut]] = None
    discrepancy_amount: Optional[float] = None
    routing_reason: Optional[str] = None
    status: str
    requires_maker_checker: Optional[bool] = False
    proposed_by: Optional[str] = None
    authorized_by: Optional[str] = None
    reasoning_card: Optional[ReasoningCardOut] = None


class ExceptionsListResponse(BaseModel):
    total: int
    items: List[ExceptionItemOut]


# ─────────────────────────────────────────────
# APPROVAL, MAKER-CHECKER & REJECTION SCHEMAS
# ─────────────────────────────────────────────

class ApproveRequest(BaseModel):
    reviewed_by: Optional[str] = "accountant_user"


class ApproveResponse(BaseModel):
    result_id: uuid.UUID
    status: str
    journal_posted: bool
    reviewed_at: datetime


class ProposeRequest(BaseModel):
    proposed_by: Optional[str] = "accountant_maker"
    note: Optional[str] = None


class ProposeResponse(BaseModel):
    result_id: uuid.UUID
    status: str
    proposed_by: str
    proposed_at: datetime
    requires_maker_checker: bool
    message: str


class AuthorizeRequest(BaseModel):
    authorized_by: Optional[str] = "controller_checker"
    note: Optional[str] = None


class AuthorizeResponse(BaseModel):
    result_id: uuid.UUID
    status: str
    proposed_by: Optional[str]
    authorized_by: str
    journal_posted: bool
    authorized_at: datetime


class RejectRequest(BaseModel):
    reviewed_by: Optional[str] = "user_default"
    override_note: Optional[str] = None


class RejectResponse(BaseModel):
    result_id: uuid.UUID
    status: str
    reviewed_at: datetime


# ─────────────────────────────────────────────
# AUDIT LOG & ACCURACY REPORT SCHEMAS
# ─────────────────────────────────────────────

class AuditLogItemOut(BaseModel):
    id: uuid.UUID
    batch_id: Optional[uuid.UUID] = None
    sequence_num: Optional[int] = None
    prev_hash: Optional[str] = None
    current_hash: Optional[str] = None
    event_type: str
    actor: str
    payload_json: Dict[str, Any]
    timestamp: datetime


class AuditLogResponse(BaseModel):
    total: int
    events: List[AuditLogItemOut]


class AuditVerifyResponse(BaseModel):
    is_valid: bool
    total_verified_events: int
    batch_events_count: Optional[int] = None
    latest_sequence: Optional[int] = None
    head_hash: Optional[str] = None
    broken_at_sequence: Optional[int] = None
    broken_row_id: Optional[str] = None
    reason: Optional[str] = None
    message: str


class AccuracyReportResponse(BaseModel):
    total_evaluated: int
    explainable_total: int
    explainable_correct: int
    explainable_accuracy_pct: float
    unresolvable_total: int
    unresolvable_correct: int
    unresolvable_accuracy_pct: float
    overall_accuracy_pct: float
    confusion_matrix: Dict[str, Any]
