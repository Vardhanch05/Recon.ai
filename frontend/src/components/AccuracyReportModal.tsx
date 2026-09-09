import React from 'react';
import { Award, ShieldCheck, X } from 'lucide-react';
import type { AccuracyReport } from '../types';

interface AccuracyReportModalProps {
  report: AccuracyReport | null;
  onClose: () => void;
  isLoading: boolean;
}

export const AccuracyReportModal: React.FC<AccuracyReportModalProps> = ({ report, onClose, isLoading }) => {
  if (!report && !isLoading) return null;

  return (
    <div style={{
      position: 'fixed',
      top: 0,
      left: 0,
      right: 0,
      bottom: 0,
      background: 'rgba(0, 0, 0, 0.8)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 1100,
      padding: '24px'
    }}>
      <div className="glass-card" style={{ maxWidth: '680px', width: '100%', padding: '32px', background: 'var(--bg-card)' }}>
        
        {/* Modal Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <div style={{
              width: '38px',
              height: '38px',
              borderRadius: '10px',
              background: 'rgba(139, 92, 246, 0.2)',
              border: '1px solid rgba(139, 92, 246, 0.4)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#a78bfa'
            }}>
              <Award size={22} />
            </div>
            <div>
              <h3 style={{ fontSize: '18px', fontWeight: 800 }}>Live Verifiable Accuracy Report</h3>
              <p style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                Evaluated live against hidden ground truth answer key (<code>ground_truth.csv</code>)
              </p>
            </div>
          </div>

          <button onClick={onClose} className="btn btn-secondary" style={{ padding: '6px 10px' }}>
            <X size={16} />
          </button>
        </div>

        {isLoading ? (
          <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-secondary)' }}>
            Evaluating reasoner cards against ground truth...
          </div>
        ) : report ? (
          <>
            {/* Accuracy Score Banner */}
            <div style={{
              padding: '20px',
              background: 'linear-gradient(135deg, rgba(16, 185, 129, 0.15) 0%, rgba(51, 149, 255, 0.15) 100%)',
              border: '1px solid rgba(16, 185, 129, 0.3)',
              borderRadius: 'var(--radius-md)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              marginBottom: '24px'
            }}>
              <div>
                <div style={{ fontSize: '12px', fontWeight: 700, color: 'var(--text-secondary)', textTransform: 'uppercase' }}>
                  Overall Verification Accuracy
                </div>
                <div style={{ fontSize: '32px', fontWeight: 900, color: '#34d399', letterSpacing: '-0.02em' }}>
                  {report.overall_accuracy_pct.toFixed(1)}%
                </div>
              </div>
              <div style={{ textAlign: 'right' }}>
                <span className="badge badge-green" style={{ fontSize: '12px', padding: '4px 10px' }}>
                  <ShieldCheck size={14} /> 100% Honesty Invariant
                </span>
                <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '4px' }}>
                  {report.explainable_correct + report.unresolvable_correct} / {report.total_evaluated} Non-Trivial Records
                </div>
              </div>
            </div>

            {/* Metrics Breakdown */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '24px' }}>
              <div style={{ padding: '16px', background: 'var(--bg-inset)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
                <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Explainable Discrepancies</div>
                <div style={{ fontSize: '20px', fontWeight: 700, color: '#a78bfa', marginTop: '2px' }}>
                  {report.explainable_correct} of {report.explainable_total} ({report.explainable_accuracy_pct.toFixed(1)}%)
                </div>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>
                  MDR fees, GST, partial refunds, FX variances correctly identified.
                </div>
              </div>

              <div style={{ padding: '16px', background: 'var(--bg-inset)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
                <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Unresolvable Records (No Hallucination)</div>
                <div style={{ fontSize: '20px', fontWeight: 700, color: '#f87171', marginTop: '2px' }}>
                  {report.unresolvable_correct} of {report.unresolvable_total} ({report.unresolvable_accuracy_pct.toFixed(1)}%)
                </div>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>
                  Correctly flagged UNRESOLVED with zero fabricated explanations.
                </div>
              </div>
            </div>

            {/* Category breakdown table */}
            <div>
              <div style={{ fontSize: '12px', fontWeight: 700, color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: '10px' }}>
                Category-by-Category Performance
              </div>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border-subtle)', color: 'var(--text-muted)', textAlign: 'left' }}>
                    <th style={{ padding: '8px 4px' }}>Category</th>
                    <th style={{ padding: '8px 4px', textAlign: 'center' }}>Tested Records</th>
                    <th style={{ padding: '8px 4px', textAlign: 'center' }}>Correct</th>
                    <th style={{ padding: '8px 4px', textAlign: 'right' }}>Accuracy</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(report.confusion_matrix.category_breakdown || {}).map(([cat, stats]) => (
                    <tr key={cat} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                      <td style={{ padding: '8px 4px', fontWeight: 600 }}>{cat}</td>
                      <td style={{ padding: '8px 4px', textAlign: 'center' }}>{stats.total}</td>
                      <td style={{ padding: '8px 4px', textAlign: 'center', color: '#34d399' }}>{stats.correct}</td>
                      <td style={{ padding: '8px 4px', textAlign: 'right', fontWeight: 700, color: stats.correct === stats.total ? '#34d399' : '#f87171' }}>
                        {((stats.correct / stats.total) * 100).toFixed(1)}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div style={{ marginTop: '24px', textAlign: 'right' }}>
              <button onClick={onClose} className="btn btn-primary" style={{ padding: '8px 24px' }}>
                Done
              </button>
            </div>
          </>
        ) : null}

      </div>
    </div>
  );
};
