import uuid
import enum
from datetime import datetime
from sqlalchemy import (
    Column,
    String,
    Integer,
    Numeric,
    DateTime,
    Boolean,
    Text,
    ForeignKey,
    Enum as SQLEnum,
    Index,
    UniqueConstraint
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.types import TypeDecorator, CHAR
from sqlalchemy.orm import relationship

from backend.database import Base

# Universal UUID type that works across PostgreSQL and SQLite
class GUID(TypeDecorator):
    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            return dialect.type_descriptor(UUID())
        else:
            return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        elif dialect.name == 'postgresql':
            return str(value)
        else:
            if isinstance(value, uuid.UUID):
                return str(value)
            else:
                return str(uuid.UUID(value))

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        else:
            if not isinstance(value, uuid.UUID):
                value = uuid.UUID(value)
            return value


# Universal JSON type that uses JSONB on PostgreSQL and JSON/Text on SQLite
class JSONType(TypeDecorator):
    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            return dialect.type_descriptor(JSONB())
        else:
            from sqlalchemy import JSON
            return dialect.type_descriptor(JSON())

    def process_bind_param(self, value, dialect):
        return value

    def process_result_value(self, value, dialect):
        return value


# ─────────────────────────────────────────────
# ENUMS
# ─────────────────────────────────────────────

class BatchStatus(str, enum.Enum):
    uploaded = "uploaded"
    matching_complete = "matching_complete"
    reasoning_complete = "reasoning_complete"
    failed = "failed"


class ReconciliationStatus(str, enum.Enum):
    matched_deterministic = "matched_deterministic"
    matched_ai_resolved = "matched_ai_resolved"
    exception_unresolved = "exception_unresolved"
    human_approved = "human_approved"
    human_rejected = "human_rejected"


class RoutingReason(str, enum.Enum):
    order_id_match = "order_id_match"
    amount_match = "amount_match"
    amount_mismatch = "amount_mismatch"
    no_match = "no_match"
    ambiguous_multiple = "ambiguous_multiple"
    currency_mismatch = "currency_mismatch"


class ResolutionSource(str, enum.Enum):
    rule_engine = "rule_engine"
    llm_reasoner = "llm_reasoner"
    human_override = "human_override"


class AuditEventType(str, enum.Enum):
    ingestion_error = "ingestion_error"
    match = "match"
    llm_call = "llm_call"
    human_approval = "human_approval"
    human_rejection = "human_rejection"
    journal_posted = "journal_posted"


# ─────────────────────────────────────────────
# MODELS
# ─────────────────────────────────────────────

class Batch(Base):
    __tablename__ = "batches"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    uploaded_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    status = Column(SQLEnum(BatchStatus, name="batch_status"), nullable=False, default=BatchStatus.uploaded)
    total_records = Column(Integer, nullable=True)
    ingestion_error_count = Column(Integer, nullable=False, default=0)
    match_rate_deterministic = Column(Numeric(5, 2), nullable=True)
    match_rate_ai_resolved = Column(Numeric(5, 2), nullable=True)
    unresolved_count = Column(Integer, nullable=True)
    timestamp_tolerance_seconds = Column(Integer, nullable=False, default=2)

    # Relationships
    settlement_records = relationship("SettlementRecord", back_populates="batch", cascade="all, delete-orphan")
    order_ledger_records = relationship("OrderLedger", back_populates="batch", cascade="all, delete-orphan")
    reconciliation_results = relationship("ReconciliationResult", back_populates="batch", cascade="all, delete-orphan")


class SettlementRecord(Base):
    __tablename__ = "settlement_records"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    batch_id = Column(GUID(), ForeignKey("batches.id", ondelete="CASCADE"), nullable=False, index=True)
    gateway_txn_id = Column(String, nullable=False)
    order_id = Column(String, nullable=True)
    settled_amount = Column(Numeric(12, 2), nullable=False)
    settlement_timestamp = Column(DateTime, nullable=False)
    fee_deducted = Column(Numeric(12, 2), nullable=True)
    currency = Column(String(3), nullable=False, default="INR")
    raw_row_json = Column(JSONType(), nullable=False)

    # Relationships & Constraints
    batch = relationship("Batch", back_populates="settlement_records")
    reconciliation_result = relationship("ReconciliationResult", back_populates="settlement_record", uselist=False)

    __table_args__ = (
        UniqueConstraint("batch_id", "gateway_txn_id", name="uq_settlement_txn"),
    )


class OrderLedger(Base):
    __tablename__ = "order_ledger"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    batch_id = Column(GUID(), ForeignKey("batches.id", ondelete="CASCADE"), nullable=False, index=True)
    order_id = Column(String, nullable=False)
    billed_amount = Column(Numeric(12, 2), nullable=False)
    order_timestamp = Column(DateTime, nullable=False)
    refund_amount = Column(Numeric(12, 2), nullable=True)
    is_international = Column(Boolean, nullable=False, default=False)
    payment_method = Column(String, nullable=True)
    raw_row_json = Column(JSONType(), nullable=False)

    # Relationships
    batch = relationship("Batch", back_populates="order_ledger_records")


class ReconciliationResult(Base):
    __tablename__ = "reconciliation_results"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    batch_id = Column(GUID(), ForeignKey("batches.id", ondelete="CASCADE"), nullable=False, index=True)
    settlement_record_id = Column(GUID(), ForeignKey("settlement_records.id"), nullable=False)
    order_ledger_id = Column(GUID(), ForeignKey("order_ledger.id"), nullable=True)
    status = Column(
        SQLEnum(ReconciliationStatus, name="reconciliation_status"),
        nullable=False,
        default=ReconciliationStatus.exception_unresolved
    )
    routing_reason = Column(SQLEnum(RoutingReason, name="routing_reason"), nullable=True)
    discrepancy_amount = Column(Numeric(12, 2), nullable=True)
    resolution_source = Column(SQLEnum(ResolutionSource, name="resolution_source"), nullable=True)
    confidence_score = Column(Numeric(3, 2), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    reviewed_by = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships & Constraints
    batch = relationship("Batch", back_populates="reconciliation_results")
    settlement_record = relationship("SettlementRecord", back_populates="reconciliation_result")
    order_ledger = relationship("OrderLedger")
    exception_candidates = relationship("ExceptionCandidate", back_populates="reconciliation_result", cascade="all, delete-orphan")
    reasoning_card = relationship("ReasoningCard", back_populates="reconciliation_result", uselist=False, cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("batch_id", "settlement_record_id", name="uq_result_per_settlement"),
        Index("idx_results_status", "batch_id", "status"),
    )


class ExceptionCandidate(Base):
    __tablename__ = "exception_candidates"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    reconciliation_result_id = Column(GUID(), ForeignKey("reconciliation_results.id", ondelete="CASCADE"), nullable=False)
    order_ledger_id = Column(GUID(), ForeignKey("order_ledger.id"), nullable=False)

    # Relationships & Constraints
    reconciliation_result = relationship("ReconciliationResult", back_populates="exception_candidates")
    order_ledger = relationship("OrderLedger")

    __table_args__ = (
        UniqueConstraint("reconciliation_result_id", "order_ledger_id", name="uq_candidate"),
    )


class ReasoningCard(Base):
    __tablename__ = "reasoning_cards"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    reconciliation_result_id = Column(GUID(), ForeignKey("reconciliation_results.id", ondelete="CASCADE"), nullable=False)
    hypothesis_text = Column(Text, nullable=False)
    calculation_breakdown = Column(JSONType(), nullable=False)
    confidence_score = Column(Numeric(3, 2), nullable=False)
    suggested_category = Column(String, nullable=False)
    requires_human_review = Column(Boolean, nullable=False, default=True)
    human_override_note = Column(Text, nullable=True)

    # Relationships & Constraints
    reconciliation_result = relationship("ReconciliationResult", back_populates="reasoning_card")

    __table_args__ = (
        UniqueConstraint("reconciliation_result_id", name="uq_reasoning_card_result"),
        Index("idx_cards_result", "reconciliation_result_id"),
    )


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    batch_id = Column(GUID(), nullable=False)
    event_type = Column(SQLEnum(AuditEventType, name="audit_event_type"), nullable=False)
    actor = Column(String, nullable=False)
    payload_json = Column(JSONType(), nullable=False)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_audit_batch_time", "batch_id", "timestamp"),
    )
