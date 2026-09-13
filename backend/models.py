import uuid
import enum
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Float, Integer, Boolean, DateTime, ForeignKey, Enum as SQLEnum,
    Text, Index, UniqueConstraint, Numeric, types, event
)
from sqlalchemy.orm import relationship

try:
    from backend.database import Base
except ImportError:
    from database import Base


class ImmutableRecordError(Exception):
    """Raised when an update or delete operation is attempted on an immutable record."""
    pass

def get_utc_now() -> datetime:
    """Returns current naive UTC timestamp."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

# Cross-database GUID type supporting both PostgreSQL and SQLite
class GUID(types.TypeDecorator):
    """Platform-independent GUID type.
    Uses PostgreSQL's UUID type, otherwise uses CHAR(36), storing as stringifier.
    """
    impl = types.CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            from sqlalchemy.dialects.postgresql import UUID
            return dialect.type_descriptor(UUID(as_uuid=True))
        else:
            return dialect.type_descriptor(types.CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        elif dialect.name == 'postgresql':
            return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
        else:
            return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))


class BatchStatus(str, enum.Enum):
    uploaded = "uploaded"
    matching_in_progress = "matching_in_progress"
    matching_complete = "matching_complete"
    reasoning_in_progress = "reasoning_in_progress"
    reasoning_complete = "reasoning_complete"
    approved = "approved"
    failed = "failed"


class ReconciliationStatus(str, enum.Enum):
    matched_deterministic = "matched_deterministic"
    matched_ai_resolved = "matched_ai_resolved"
    pending_authorization = "pending_authorization"
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


class DiscrepancyCategory(str, enum.Enum):
    MDR_VARIANCE = "MDR_VARIANCE"
    PARTIAL_REFUND = "PARTIAL_REFUND"
    FX_ROUNDING = "FX_ROUNDING"
    DOMESTIC_MDR = "DOMESTIC_MDR"
    INTERNATIONAL_MDR = "INTERNATIONAL_MDR"
    GST_ON_FEE = "GST_ON_FEE"
    FLAT_SURCHARGE = "FLAT_SURCHARGE"
    COMBINED_DISCREPANCY = "COMBINED_DISCREPANCY"
    UNRESOLVED = "UNRESOLVED"


class AuditEventType(str, enum.Enum):
    ingestion_error = "ingestion_error"
    match = "match"
    llm_call = "llm_call"
    human_proposal = "human_proposal"
    human_approval = "human_approval"
    human_rejection = "human_rejection"
    journal_posted = "journal_posted"


class Batch(Base):
    __tablename__ = "batches"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    uploaded_at = Column(DateTime, default=get_utc_now, nullable=False)
    status = Column(SQLEnum(BatchStatus), default=BatchStatus.uploaded, nullable=False)
    total_records = Column(Integer, default=0)
    ingestion_error_count = Column(Integer, default=0)
    matched_deterministic_count = Column(Integer, default=0)
    matched_ai_resolved_count = Column(Integer, default=0)
    match_rate_deterministic = Column(Numeric(5, 2), nullable=True)
    match_rate_ai_resolved = Column(Numeric(5, 2), nullable=True)
    unresolved_count = Column(Integer, default=0)
    timestamp_tolerance_seconds = Column(Integer, default=2)
    duration_ms = Column(Integer, default=0)

    # Relationships
    settlements = relationship("SettlementRecord", back_populates="batch", cascade="all, delete-orphan")
    ledger_entries = relationship("OrderLedger", back_populates="batch", cascade="all, delete-orphan")
    results = relationship("ReconciliationResult", back_populates="batch", cascade="all, delete-orphan")
    # Audit logs are immutable and must NOT be deleted when a batch is deleted
    audit_logs = relationship("AuditLog", back_populates="batch")


class SettlementRecord(Base):
    __tablename__ = "settlement_records"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    batch_id = Column(GUID, ForeignKey("batches.id", ondelete="CASCADE"), nullable=False)
    gateway_txn_id = Column(String, nullable=False)
    order_id = Column(String, nullable=True, index=True)
    settled_amount = Column(Numeric(18, 4), nullable=False)
    settlement_timestamp = Column(DateTime, nullable=False)
    fee_deducted = Column(Numeric(18, 4), nullable=True)
    currency = Column(String(3), default="INR")
    raw_row_json = Column(Text, nullable=True)

    batch = relationship("Batch", back_populates="settlements")

    __table_args__ = (
        UniqueConstraint("batch_id", "gateway_txn_id", name="uq_batch_gateway_txn"),
    )


class OrderLedger(Base):
    __tablename__ = "order_ledger"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    batch_id = Column(GUID, ForeignKey("batches.id", ondelete="CASCADE"), nullable=False)
    order_id = Column(String, nullable=False, index=True)
    billed_amount = Column(Numeric(18, 4), nullable=False)
    order_timestamp = Column(DateTime, nullable=False)
    refund_amount = Column(Numeric(18, 4), default=0.0, nullable=True)
    is_international = Column(Boolean, default=False)
    payment_method = Column(String, default="card")
    raw_row_json = Column(Text, nullable=True)

    batch = relationship("Batch", back_populates="ledger_entries")


class ReconciliationResult(Base):
    __tablename__ = "reconciliation_results"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    batch_id = Column(GUID, ForeignKey("batches.id", ondelete="CASCADE"), nullable=False)
    settlement_record_id = Column(GUID, ForeignKey("settlement_records.id", ondelete="CASCADE"), nullable=False)
    order_ledger_id = Column(GUID, ForeignKey("order_ledger.id", ondelete="SET NULL"), nullable=True)
    
    status = Column(SQLEnum(ReconciliationStatus), nullable=False)
    routing_reason = Column(SQLEnum(RoutingReason), nullable=True)
    discrepancy_amount = Column(Numeric(18, 4), nullable=True)
    resolution_source = Column(SQLEnum(ResolutionSource), default=ResolutionSource.rule_engine, nullable=False)
    confidence_score = Column(Numeric(5, 4), nullable=True)
    
    # Maker-Checker Fields
    requires_maker_checker = Column(Boolean, default=False)
    proposed_by = Column(String, nullable=True)
    proposed_at = Column(DateTime, nullable=True)
    authorized_by = Column(String, nullable=True)
    authorized_at = Column(DateTime, nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    reviewed_by = Column(String, nullable=True)
    created_at = Column(DateTime, default=get_utc_now)

    batch = relationship("Batch", back_populates="results")
    settlement_record = relationship("SettlementRecord")
    order_ledger = relationship("OrderLedger")
    reasoning_card = relationship("ReasoningCard", uselist=False, back_populates="reconciliation_result", cascade="all, delete-orphan")
    exception_candidates = relationship("ExceptionCandidate", back_populates="reconciliation_result", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("batch_id", "settlement_record_id", name="uq_batch_settlement_reconciliation"),
    )


class ExceptionCandidate(Base):
    __tablename__ = "exception_candidates"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    reconciliation_result_id = Column(GUID, ForeignKey("reconciliation_results.id", ondelete="CASCADE"), nullable=False)
    order_ledger_id = Column(GUID, ForeignKey("order_ledger.id", ondelete="CASCADE"), nullable=False)

    reconciliation_result = relationship("ReconciliationResult", back_populates="exception_candidates")
    order_ledger = relationship("OrderLedger")


class ReasoningCard(Base):
    __tablename__ = "reasoning_cards"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    reconciliation_result_id = Column(GUID, ForeignKey("reconciliation_results.id", ondelete="CASCADE"), unique=True, nullable=False)
    
    hypothesis_text = Column(Text, nullable=False)
    calculation_breakdown = Column(Text, nullable=False)  # JSON string
    confidence_score = Column(Numeric(5, 4), nullable=False)
    suggested_category = Column(SQLEnum(DiscrepancyCategory, name="discrepancy_category_enum"), nullable=False)
    requires_human_review = Column(Boolean, default=True)
    human_override_note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=get_utc_now)

    reconciliation_result = relationship("ReconciliationResult", back_populates="reasoning_card")


class AuditChainHead(Base):
    """
    Singleton table holding the latest cryptographic head hash and sequence number.
    Row with id=1 is locked via FOR UPDATE in PostgreSQL / Lock in SQLite to serialize writes atomically.
    """
    __tablename__ = "audit_chain_head"

    id = Column(Integer, primary_key=True, default=1)
    current_hash = Column(String(64), nullable=False)
    sequence_num = Column(Integer, default=0, nullable=False)
    updated_at = Column(DateTime, default=get_utc_now, onupdate=get_utc_now)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    batch_id = Column(GUID, ForeignKey("batches.id", ondelete="SET NULL"), nullable=True)
    sequence_num = Column(Integer, nullable=True, index=True)
    prev_hash = Column(String(64), nullable=True)
    current_hash = Column(String(64), nullable=True)
    event_type = Column(SQLEnum(AuditEventType), nullable=False)
    actor = Column(String, default="system", nullable=False)
    payload_json = Column(Text, nullable=True)  # Canonical JSON string
    timestamp = Column(DateTime, default=get_utc_now, nullable=False)

    batch = relationship("Batch", back_populates="audit_logs")

    __table_args__ = (
        Index("idx_audit_batch_time", "batch_id", "timestamp"),
        Index("idx_audit_sequence", "sequence_num"),
    )


# --- ORM-level Immutability Enforcement for AuditLog ---
@event.listens_for(AuditLog, "before_update")
def _prevent_audit_log_update(mapper, connection, target):
    from sqlalchemy import inspect
    state = inspect(target)
    for attr in state.attrs:
        if attr.key in ("event_type", "actor", "payload_json", "timestamp", "sequence_num", "prev_hash", "current_hash") and attr.history.has_changes():
            raise ImmutableRecordError("AuditLog records are immutable and cannot be updated.")


@event.listens_for(AuditLog, "before_delete")
def _prevent_audit_log_delete(mapper, connection, target):
    raise ImmutableRecordError("AuditLog records are immutable and cannot be deleted.")
