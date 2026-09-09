import React, { useState } from 'react';
import {
  Check,
  X,
  ChevronDown,
  ChevronUp,
  Calculator,
  Lock,
  MessageSquare
} from 'lucide-react';
import type { ExceptionItem } from '../types';

interface ReasoningCardProps {
  item: ExceptionItem;
  onApprove: (id: string) => Promise<void>;
  onReject: (id: string, note?: string) => Promise<void>;
}

export const ReasoningCard: React.FC<ReasoningCardProps> = ({ item, onApprove, onReject }) => {
  const [isExpanded, setIsExpanded] = useState(false);
  const [showRejectModal, setShowRejectModal] = useState(false);
  const [rejectNote, setRejectNote] = useState('');
  const [actionLoading, setActionLoading] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const card = item.reasoning_card;
  const isUnresolved = !card || card.suggested_category === 'UNRESOLVED' || card.confidence_score === 0;
  const isApproved = item.status === 'human_approved';
  const isRejected = item.status === 'human_rejected';
  const isActioned = isApproved || isRejected;

  const handleApprove = async () => {
    setActionLoading(true);
    setActionError(null);
    try {
      await onApprove(item.reconciliation_result_id);
    } catch (err: any) {
      setActionError(err.message || 'Approval failed');
    } finally {
      setActionLoading(false);
    }
  };

  const handleRejectConfirm = async () => {
    setActionLoading(true);
    setActionError(null);
    try {
      await onReject(item.reconciliation_result_id, rejectNote);
      setShowRejectModal(false);
    } catch (err: any) {
      setActionError(err.message || 'Rejection failed');
    } finally {
      setActionLoading(false);
    }
  };

  const getConfidenceBadge = (score: number) => {
    if (score >= 0.94) {
      return <span className="badge badge-green">Confidence {score.toFixed(2)}</span>;
    } else if (score >= 0.50) {
      return <span className="badge badge-amber">Low Confidence {score.toFixed(2)}</span>;
    } else {
      return <span className="badge badge-red">Unresolved 0.00</span>;
    }
  };

  const getCategoryBadge = (category: string) => {
    switch (category) {
      case 'MDR_VARIANCE':
        return <span className="badge badge-blue">MDR Variance</span>;
      case 'PARTIAL_REFUND':
        return <span className="badge badge-purple">Partial Refund</span>;
      case 'FX_ROUNDING':
        return <span className="badge badge-amber">FX Rounding</span>;
      default:
        return <span className="badge badge-red">Unresolved Exception</span>;
    }
  };

  const calc = card?.calculation_breakdown;

  return (
    <div
      className="glass-card"
      style={{
        padding: '24px',
        marginBottom: '16px',
        borderLeft: `4px solid ${
          isApproved
            ? 'var(--accent-green)'
            : isRejected
            ? 'var(--accent-red)'
            : isUnresolved
            ? 'var(--accent-red)'
            : 'var(--accent-purple)'
        }`,
        background: isActioned ? 'rgba(17, 22, 34, 0.6)' : 'var(--bg-card)'
      }}
    >
      {/* Header Bar */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '16px', flexWrap: 'wrap' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
            <span style={{ fontSize: '15px', fontWeight: 700, color: 'var(--text-primary)' }}>
              {item.settlement_record.gateway_txn_id}
            </span>
            {item.settlement_record.order_id && (
              <span style={{ fontSize: '13px', color: 'var(--text-secondary)', background: 'var(--bg-inset)', padding: '2px 8px', borderRadius: '4px' }}>
                Order: {item.settlement_record.order_id}
              </span>
            )}
            {card && getCategoryBadge(card.suggested_category)}
            {card && getConfidenceBadge(card.confidence_score)}
            {isApproved && <span className="badge badge-green"><Check size={12} /> Approved & Posted</span>}
            {isRejected && <span className="badge badge-red"><X size={12} /> Rejected</span>}
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '16px', marginTop: '8px', fontSize: '13px', color: 'var(--text-secondary)' }}>
            <span>Settled: <strong style={{ color: 'var(--text-primary)' }}>₹{item.settlement_record.settled_amount.toFixed(2)}</strong></span>
            {item.candidate_orders && item.candidate_orders.length > 0 && (
              <span>Billed: <strong style={{ color: 'var(--text-primary)' }}>₹{item.candidate_orders[0].billed_amount.toFixed(2)}</strong></span>
            )}
            {item.discrepancy_amount && item.discrepancy_amount > 0 && (
              <span style={{ color: '#f87171' }}>
                Discrepancy: <strong>₹{item.discrepancy_amount.toFixed(2)}</strong>
              </span>
            )}
          </div>
        </div>

        {/* Action Controls */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          {!isActioned && (
            <>
              {/* Strict hard-gate: Disable or hide Approve for UNRESOLVED */}
              {!isUnresolved ? (
                <button
                  onClick={handleApprove}
                  disabled={actionLoading}
                  className="btn btn-success"
                  style={{ padding: '8px 16px', fontSize: '13px' }}
                >
                  <Check size={15} />
                  <span>Approve & Post</span>
                </button>
              ) : (
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', color: 'var(--text-muted)', padding: '0 8px' }}>
                  <Lock size={13} />
                  <span>Approval Locked (Unresolved)</span>
                </div>
              )}

              <button
                onClick={() => setShowRejectModal(true)}
                disabled={actionLoading}
                className="btn btn-danger"
                style={{ padding: '8px 16px', fontSize: '13px' }}
              >
                <X size={15} />
                <span>{isUnresolved ? 'Route to Manual' : 'Reject'}</span>
              </button>
            </>
          )}

          <button
            onClick={() => setIsExpanded(!isExpanded)}
            className="btn btn-secondary"
            style={{ padding: '8px 12px', fontSize: '13px' }}
            title="Toggle Math Breakdown"
          >
            <Calculator size={15} />
            {isExpanded ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
          </button>
        </div>
      </div>

      {actionError && (
        <div style={{ marginTop: '12px', padding: '8px 12px', background: 'rgba(239, 68, 68, 0.15)', borderRadius: 'var(--radius-sm)', color: '#f87171', fontSize: '12px' }}>
          {actionError}
        </div>
      )}

      {/* Hypothesis Prose */}
      {card && (
        <div style={{
          marginTop: '16px',
          padding: '12px 16px',
          background: 'var(--bg-inset)',
          borderRadius: 'var(--radius-md)',
          fontSize: '13px',
          lineHeight: '1.6',
          color: isUnresolved ? '#fca5a5' : '#e2e8f0',
          border: '1px solid var(--border-subtle)'
        }}>
          <strong>AI Analysis:</strong> {card.hypothesis_text}
        </div>
      )}

      {/* Expandable Calculation Breakdown Table */}
      {isExpanded && calc && (
        <div style={{ marginTop: '16px', borderTop: '1px solid var(--border-subtle)', paddingTop: '16px' }}>
          <div style={{ fontSize: '12px', fontWeight: 700, color: 'var(--text-secondary)', marginBottom: '10px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            Isolated Arithmetic Verification Table
          </div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
            <tbody>
              {calc.billed_amount !== undefined && (
                <tr style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                  <td style={{ padding: '8px 0', color: 'var(--text-secondary)' }}>Billed Amount</td>
                  <td style={{ padding: '8px 0', textAlign: 'right', fontWeight: 600 }}>₹{calc.billed_amount.toFixed(2)}</td>
                </tr>
              )}
              {calc.fee_pct_tested !== undefined && calc.fee_pct_tested > 0 && (
                <tr style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                  <td style={{ padding: '8px 0', color: 'var(--text-secondary)' }}>Estimated Fee ({calc.fee_pct_tested}% MDR)</td>
                  <td style={{ padding: '8px 0', textAlign: 'right', color: '#f87171' }}>
                    -₹{((calc.billed_amount || 0) * (calc.fee_pct_tested / 100)).toFixed(2)}
                  </td>
                </tr>
              )}
              {calc.gst_on_fee_pct_tested !== undefined && calc.gst_on_fee_pct_tested > 0 && (
                <tr style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                  <td style={{ padding: '8px 0', color: 'var(--text-secondary)' }}>GST on Fee ({calc.gst_on_fee_pct_tested}%)</td>
                  <td style={{ padding: '8px 0', textAlign: 'right', color: '#f87171' }}>
                    -₹{(((calc.billed_amount || 0) * ((calc.fee_pct_tested || 0) / 100)) * (calc.gst_on_fee_pct_tested / 100)).toFixed(2)}
                  </td>
                </tr>
              )}
              {calc.flat_surcharge_tested !== undefined && calc.flat_surcharge_tested > 0 && (
                <tr style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                  <td style={{ padding: '8px 0', color: 'var(--text-secondary)' }}>Gateway Flat Surcharge</td>
                  <td style={{ padding: '8px 0', textAlign: 'right', color: '#f87171' }}>-₹{calc.flat_surcharge_tested.toFixed(2)}</td>
                </tr>
              )}
              {calc.refund_amount_tested !== undefined && calc.refund_amount_tested > 0 && (
                <tr style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                  <td style={{ padding: '8px 0', color: 'var(--text-secondary)' }}>Customer Partial Refund</td>
                  <td style={{ padding: '8px 0', textAlign: 'right', color: '#f87171' }}>-₹{calc.refund_amount_tested.toFixed(2)}</td>
                </tr>
              )}
              {calc.expected_settlement !== undefined && (
                <tr style={{ borderBottom: '1px solid var(--border-subtle)', background: 'rgba(51, 149, 255, 0.05)' }}>
                  <td style={{ padding: '8px 6px', fontWeight: 600 }}>Expected Net Settlement</td>
                  <td style={{ padding: '8px 6px', textAlign: 'right', fontWeight: 700, color: 'var(--accent-blue)' }}>
                    ₹{calc.expected_settlement.toFixed(2)}
                  </td>
                </tr>
              )}
              <tr style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                <td style={{ padding: '8px 6px', fontWeight: 600 }}>Actual Gateway Settlement</td>
                <td style={{ padding: '8px 6px', textAlign: 'right', fontWeight: 700, color: 'var(--text-primary)' }}>
                  ₹{(calc.actual_settlement || item.settlement_record.settled_amount).toFixed(2)}
                </td>
              </tr>
              <tr style={{ background: calc.residual_gap === 0 ? 'rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.1)' }}>
                <td style={{ padding: '8px 6px', fontWeight: 700 }}>
                  Residual Gap (Difference)
                </td>
                <td style={{ padding: '8px 6px', textAlign: 'right', fontWeight: 800, color: calc.residual_gap === 0 ? '#34d399' : '#f87171' }}>
                  ₹{Math.abs(calc.residual_gap).toFixed(2)} {calc.residual_gap === 0 ? '(Exact Match)' : '(Unexplained)'}
                </td>
              </tr>
            </tbody>
          </table>

          {calc.attempts_tried && calc.attempts_tried.length > 0 && (
            <div style={{ marginTop: '12px', fontSize: '12px', color: 'var(--text-muted)' }}>
              <strong>Hypotheses Evaluated:</strong> {calc.attempts_tried.join(', ')}
            </div>
          )}
        </div>
      )}

      {/* Reject Modal */}
      {showRejectModal && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background: 'rgba(0, 0, 0, 0.75)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 1000,
          padding: '20px'
        }}>
          <div className="glass-card" style={{ maxWidth: '480px', width: '100%', padding: '24px', background: 'var(--bg-card)' }}>
            <h3 style={{ fontSize: '16px', fontWeight: 700, marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <MessageSquare size={18} color="var(--accent-red)" />
              {isUnresolved ? 'Flag for Manual Investigation' : 'Reject AI Hypothesis'}
            </h3>
            <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginBottom: '16px' }}>
              Provide an optional note explaining why this card is being rejected or routed to manual review.
            </p>

            <textarea
              rows={3}
              placeholder="e.g., Looks like an unrecorded chargeback or bank adjustment..."
              value={rejectNote}
              onChange={(e) => setRejectNote(e.target.value)}
              style={{
                width: '100%',
                padding: '10px 12px',
                background: 'var(--bg-inset)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-md)',
                color: 'var(--text-primary)',
                fontSize: '13px',
                marginBottom: '20px',
                resize: 'vertical'
              }}
            />

            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: '10px' }}>
              <button
                type="button"
                onClick={() => setShowRejectModal(false)}
                className="btn btn-secondary"
                style={{ padding: '8px 16px' }}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleRejectConfirm}
                disabled={actionLoading}
                className="btn btn-danger"
                style={{ padding: '8px 16px' }}
              >
                {actionLoading ? 'Saving...' : 'Confirm Rejection'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
