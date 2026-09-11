"""initial schema

Revision ID: 001_initial_schema
Revises: 
Create Date: 2026-09-05 21:55:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Batches Table
    op.create_table(
        'batches',
        sa.Column('id', sa.CHAR(36), primary_key=True),
        sa.Column('uploaded_at', sa.DateTime(), nullable=False),
        sa.Column('status', sa.Enum('uploaded', 'matching_in_progress', 'matching_complete', 'reasoning_in_progress', 'reasoning_complete', 'approved', 'failed', name='batch_status'), nullable=False),
        sa.Column('total_records', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('ingestion_error_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('matched_deterministic_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('matched_ai_resolved_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('match_rate_deterministic', sa.Numeric(5, 2), nullable=True),
        sa.Column('match_rate_ai_resolved', sa.Numeric(5, 2), nullable=True),
        sa.Column('unresolved_count', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('timestamp_tolerance_seconds', sa.Integer(), nullable=False, server_default='2'),
        sa.Column('duration_ms', sa.Integer(), nullable=False, server_default='0')
    )

    # 2. Settlement Records Table
    op.create_table(
        'settlement_records',
        sa.Column('id', sa.CHAR(36), primary_key=True),
        sa.Column('batch_id', sa.CHAR(36), sa.ForeignKey('batches.id', ondelete='CASCADE'), nullable=False),
        sa.Column('gateway_txn_id', sa.String(), nullable=False),
        sa.Column('order_id', sa.String(), nullable=True),
        sa.Column('settled_amount', sa.Numeric(18, 4), nullable=False),
        sa.Column('settlement_timestamp', sa.DateTime(), nullable=False),
        sa.Column('fee_deducted', sa.Numeric(18, 4), nullable=True),
        sa.Column('currency', sa.String(3), nullable=False, server_default='INR'),
        sa.Column('raw_row_json', sa.Text(), nullable=True),
        sa.UniqueConstraint('batch_id', 'gateway_txn_id', name='uq_batch_gateway_txn')
    )
    op.create_index('idx_settlement_batch', 'settlement_records', ['batch_id'])
    op.create_index('idx_settlement_order_id', 'settlement_records', ['order_id'])

    # 3. Order Ledger Table
    op.create_table(
        'order_ledger',
        sa.Column('id', sa.CHAR(36), primary_key=True),
        sa.Column('batch_id', sa.CHAR(36), sa.ForeignKey('batches.id', ondelete='CASCADE'), nullable=False),
        sa.Column('order_id', sa.String(), nullable=False),
        sa.Column('billed_amount', sa.Numeric(18, 4), nullable=False),
        sa.Column('order_timestamp', sa.DateTime(), nullable=False),
        sa.Column('refund_amount', sa.Numeric(18, 4), nullable=True, server_default='0.0'),
        sa.Column('is_international', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('payment_method', sa.String(), nullable=True, server_default='card'),
        sa.Column('raw_row_json', sa.Text(), nullable=True)
    )
    op.create_index('idx_ledger_batch', 'order_ledger', ['batch_id'])
    op.create_index('idx_ledger_order_id', 'order_ledger', ['order_id'])

    # 4. Reconciliation Results Table
    op.create_table(
        'reconciliation_results',
        sa.Column('id', sa.CHAR(36), primary_key=True),
        sa.Column('batch_id', sa.CHAR(36), sa.ForeignKey('batches.id', ondelete='CASCADE'), nullable=False),
        sa.Column('settlement_record_id', sa.CHAR(36), sa.ForeignKey('settlement_records.id', ondelete='CASCADE'), nullable=False),
        sa.Column('order_ledger_id', sa.CHAR(36), sa.ForeignKey('order_ledger.id', ondelete='SET NULL'), nullable=True),
        sa.Column('status', sa.Enum('matched_deterministic', 'matched_ai_resolved', 'exception_unresolved', 'human_approved', 'human_rejected', name='reconciliation_status'), nullable=False),
        sa.Column('routing_reason', sa.Enum('order_id_match', 'amount_match', 'amount_mismatch', 'no_match', 'ambiguous_multiple', 'currency_mismatch', name='routing_reason'), nullable=True),
        sa.Column('discrepancy_amount', sa.Numeric(18, 4), nullable=True),
        sa.Column('resolution_source', sa.Enum('rule_engine', 'llm_reasoner', 'human_override', name='resolution_source'), nullable=False, server_default='rule_engine'),
        sa.Column('confidence_score', sa.Numeric(5, 4), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('reviewed_by', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('batch_id', 'settlement_record_id', name='uq_batch_settlement_reconciliation')
    )
    op.create_index('idx_results_batch', 'reconciliation_results', ['batch_id'])
    op.create_index('idx_results_status', 'reconciliation_results', ['batch_id', 'status'])

    # 5. Exception Candidates Table
    op.create_table(
        'exception_candidates',
        sa.Column('id', sa.CHAR(36), primary_key=True),
        sa.Column('reconciliation_result_id', sa.CHAR(36), sa.ForeignKey('reconciliation_results.id', ondelete='CASCADE'), nullable=False),
        sa.Column('order_ledger_id', sa.CHAR(36), sa.ForeignKey('order_ledger.id', ondelete='CASCADE'), nullable=False)
    )

    # 6. Reasoning Cards Table
    op.create_table(
        'reasoning_cards',
        sa.Column('id', sa.CHAR(36), primary_key=True),
        sa.Column('reconciliation_result_id', sa.CHAR(36), sa.ForeignKey('reconciliation_results.id', ondelete='CASCADE'), unique=True, nullable=False),
        sa.Column('hypothesis_text', sa.Text(), nullable=False),
        sa.Column('calculation_breakdown', sa.Text(), nullable=False),
        sa.Column('confidence_score', sa.Numeric(5, 4), nullable=False),
        sa.Column('suggested_category', sa.Enum('MDR_VARIANCE', 'PARTIAL_REFUND', 'FX_ROUNDING', 'DOMESTIC_MDR', 'INTERNATIONAL_MDR', 'GST_ON_FEE', 'FLAT_SURCHARGE', 'COMBINED_DISCREPANCY', 'UNRESOLVED', name='discrepancy_category_enum'), nullable=False),
        sa.Column('requires_human_review', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('human_override_note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now())
    )
    op.create_index('idx_cards_result', 'reasoning_cards', ['reconciliation_result_id'])

    # 7. Audit Log Table
    op.create_table(
        'audit_log',
        sa.Column('id', sa.CHAR(36), primary_key=True),
        sa.Column('batch_id', sa.CHAR(36), sa.ForeignKey('batches.id', ondelete='SET NULL'), nullable=True),
        sa.Column('event_type', sa.Enum('ingestion_error', 'match', 'llm_call', 'human_approval', 'human_rejection', 'journal_posted', name='audit_event_type'), nullable=False),
        sa.Column('actor', sa.String(), nullable=False, server_default='system'),
        sa.Column('payload_json', sa.Text(), nullable=True),
        sa.Column('timestamp', sa.DateTime(), nullable=False, server_default=sa.func.now())
    )
    op.create_index('idx_audit_batch_time', 'audit_log', ['batch_id', 'timestamp'])

    # 8. PostgreSQL Database-level Immutability Trigger for audit_log
    bind = op.get_bind()
    if bind and bind.dialect.name == 'postgresql':
        op.execute("""
            CREATE OR REPLACE FUNCTION prevent_audit_log_modification()
            RETURNS TRIGGER AS $$
            BEGIN
                RAISE EXCEPTION 'audit_log table is immutable. UPDATE and DELETE are prohibited.';
            END;
            $$ LANGUAGE plpgsql;

            CREATE TRIGGER audit_log_immutability_trigger
            BEFORE UPDATE OR DELETE ON audit_log
            FOR EACH ROW
            EXECUTE FUNCTION prevent_audit_log_modification();
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind and bind.dialect.name == 'postgresql':
        op.execute("""
            DROP TRIGGER IF EXISTS audit_log_immutability_trigger ON audit_log;
            DROP FUNCTION IF EXISTS prevent_audit_log_modification();
        """)

    op.drop_table('audit_log')
    op.drop_table('reasoning_cards')
    op.drop_table('exception_candidates')
    op.drop_table('reconciliation_results')
    op.drop_table('order_ledger')
    op.drop_table('settlement_records')
    op.drop_table('batches')
