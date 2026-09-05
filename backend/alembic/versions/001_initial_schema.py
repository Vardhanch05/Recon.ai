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
        sa.Column('status', sa.Enum('uploaded', 'matching_complete', 'reasoning_complete', 'failed', name='batch_status'), nullable=False),
        sa.Column('total_records', sa.Integer(), nullable=True),
        sa.Column('ingestion_error_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('match_rate_deterministic', sa.Numeric(5, 2), nullable=True),
        sa.Column('match_rate_ai_resolved', sa.Numeric(5, 2), nullable=True),
        sa.Column('unresolved_count', sa.Integer(), nullable=True),
        sa.Column('timestamp_tolerance_seconds', sa.Integer(), nullable=False, server_default='2')
    )

    # 2. Settlement Records Table
    op.create_table(
        'settlement_records',
        sa.Column('id', sa.CHAR(36), primary_key=True),
        sa.Column('batch_id', sa.CHAR(36), sa.ForeignKey('batches.id', ondelete='CASCADE'), nullable=False),
        sa.Column('gateway_txn_id', sa.String(), nullable=False),
        sa.Column('order_id', sa.String(), nullable=True),
        sa.Column('settled_amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('settlement_timestamp', sa.DateTime(), nullable=False),
        sa.Column('fee_deducted', sa.Numeric(12, 2), nullable=True),
        sa.Column('currency', sa.String(3), nullable=False, server_default='INR'),
        sa.Column('raw_row_json', sa.Text(), nullable=False),
        sa.UniqueConstraint('batch_id', 'gateway_txn_id', name='uq_settlement_txn')
    )
    op.create_index('idx_settlement_batch', 'settlement_records', ['batch_id'])

    # 3. Order Ledger Table
    op.create_table(
        'order_ledger',
        sa.Column('id', sa.CHAR(36), primary_key=True),
        sa.Column('batch_id', sa.CHAR(36), sa.ForeignKey('batches.id', ondelete='CASCADE'), nullable=False),
        sa.Column('order_id', sa.String(), nullable=False),
        sa.Column('billed_amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('order_timestamp', sa.DateTime(), nullable=False),
        sa.Column('refund_amount', sa.Numeric(12, 2), nullable=True),
        sa.Column('is_international', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('payment_method', sa.String(), nullable=True),
        sa.Column('raw_row_json', sa.Text(), nullable=False)
    )
    op.create_index('idx_ledger_batch', 'order_ledger', ['batch_id'])

    # 4. Reconciliation Results Table
    op.create_table(
        'reconciliation_results',
        sa.Column('id', sa.CHAR(36), primary_key=True),
        sa.Column('batch_id', sa.CHAR(36), sa.ForeignKey('batches.id', ondelete='CASCADE'), nullable=False),
        sa.Column('settlement_record_id', sa.CHAR(36), sa.ForeignKey('settlement_records.id'), nullable=False),
        sa.Column('order_ledger_id', sa.CHAR(36), sa.ForeignKey('order_ledger.id'), nullable=True),
        sa.Column('status', sa.Enum('matched_deterministic', 'matched_ai_resolved', 'exception_unresolved', 'human_approved', 'human_rejected', name='reconciliation_status'), nullable=False),
        sa.Column('routing_reason', sa.Enum('order_id_match', 'amount_match', 'amount_mismatch', 'no_match', 'ambiguous_multiple', 'currency_mismatch', name='routing_reason'), nullable=True),
        sa.Column('discrepancy_amount', sa.Numeric(12, 2), nullable=True),
        sa.Column('resolution_source', sa.Enum('rule_engine', 'llm_reasoner', 'human_override', name='resolution_source'), nullable=True),
        sa.Column('confidence_score', sa.Numeric(3, 2), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('reviewed_by', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('batch_id', 'settlement_record_id', name='uq_result_per_settlement')
    )
    op.create_index('idx_results_batch', 'reconciliation_results', ['batch_id'])
    op.create_index('idx_results_status', 'reconciliation_results', ['batch_id', 'status'])

    # 5. Exception Candidates Table
    op.create_table(
        'exception_candidates',
        sa.Column('id', sa.CHAR(36), primary_key=True),
        sa.Column('reconciliation_result_id', sa.CHAR(36), sa.ForeignKey('reconciliation_results.id', ondelete='CASCADE'), nullable=False),
        sa.Column('order_ledger_id', sa.CHAR(36), sa.ForeignKey('order_ledger.id'), nullable=False),
        sa.UniqueConstraint('reconciliation_result_id', 'order_ledger_id', name='uq_candidate')
    )

    # 6. Reasoning Cards Table
    op.create_table(
        'reasoning_cards',
        sa.Column('id', sa.CHAR(36), primary_key=True),
        sa.Column('reconciliation_result_id', sa.CHAR(36), sa.ForeignKey('reconciliation_results.id', ondelete='CASCADE'), nullable=False),
        sa.Column('hypothesis_text', sa.Text(), nullable=False),
        sa.Column('calculation_breakdown', sa.Text(), nullable=False),
        sa.Column('confidence_score', sa.Numeric(3, 2), nullable=False),
        sa.Column('suggested_category', sa.String(), nullable=False),
        sa.Column('requires_human_review', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('human_override_note', sa.Text(), nullable=True),
        sa.UniqueConstraint('reconciliation_result_id', name='uq_reasoning_card_result')
    )
    op.create_index('idx_cards_result', 'reasoning_cards', ['reconciliation_result_id'])

    # 7. Audit Log Table
    op.create_table(
        'audit_log',
        sa.Column('id', sa.CHAR(36), primary_key=True),
        sa.Column('batch_id', sa.CHAR(36), nullable=False),
        sa.Column('event_type', sa.Enum('ingestion_error', 'match', 'llm_call', 'human_approval', 'human_rejection', 'journal_posted', name='audit_event_type'), nullable=False),
        sa.Column('actor', sa.String(), nullable=False),
        sa.Column('payload_json', sa.Text(), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=False)
    )
    op.create_index('idx_audit_batch_time', 'audit_log', ['batch_id', 'timestamp'])


def downgrade() -> None:
    op.drop_table('audit_log')
    op.drop_table('reasoning_cards')
    op.drop_table('exception_candidates')
    op.drop_table('reconciliation_results')
    op.drop_table('order_ledger')
    op.drop_table('settlement_records')
    op.drop_table('batches')
