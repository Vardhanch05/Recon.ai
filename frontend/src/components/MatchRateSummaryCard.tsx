import React from 'react';
import { CheckCircle, Brain, AlertTriangle, Zap, CheckCheck, TrendingUp } from 'lucide-react';
import type { BatchSummary } from '../types';

interface MatchRateSummaryCardProps {
  summary: BatchSummary;
}

export const MatchRateSummaryCard: React.FC<MatchRateSummaryCardProps> = ({ summary }) => {
  const total = summary.total_records || 1;
  const detRate = summary.match_rate_deterministic_pct !== null ? summary.match_rate_deterministic_pct : (summary.matched_deterministic_count / total * 100);
  const aiRate = summary.match_rate_ai_resolved_pct !== null ? summary.match_rate_ai_resolved_pct : (summary.matched_ai_resolved_count / total * 100);
  const unresRate = summary.unresolved_count ? (summary.unresolved_count / total * 100) : 0;

  const totalReconciledPct = (summary.matched_deterministic_count + summary.matched_ai_resolved_count) / total * 100;

  return (
    <div className="glass-card" style={{ padding: '28px', marginBottom: '32px' }}>
      
      {/* Header bar */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '24px' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <TrendingUp size={20} color="var(--accent-blue)" />
            <h2 style={{ fontSize: '18px', fontWeight: 700 }}>Settlement Match Rate Breakdown</h2>
          </div>
          <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '2px' }}>
            Multi-stage reconciliation progress across deterministic rule-matching and AI discrepancy reasoning
          </p>
        </div>

        {summary.throughput_ms && (
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            background: 'rgba(51, 149, 255, 0.1)',
            border: '1px solid rgba(51, 149, 255, 0.25)',
            padding: '6px 14px',
            borderRadius: '20px',
            fontSize: '12px',
            fontWeight: 600,
            color: '#60a5fa'
          }}>
            <Zap size={14} />
            <span>{(summary.throughput_ms / 1000).toFixed(2)}s Total Pipeline Speed</span>
          </div>
        )}
      </div>

      {/* Multi-segment Progress Bar */}
      <div style={{ marginBottom: '24px' }}>
        <div style={{
          height: '14px',
          width: '100%',
          background: 'var(--bg-inset)',
          borderRadius: '7px',
          overflow: 'hidden',
          display: 'flex',
          border: '1px solid var(--border-subtle)'
        }}>
          <div
            style={{
              width: `${detRate}%`,
              background: 'linear-gradient(90deg, #10b981, #34d399)',
              transition: 'width 0.8s cubic-bezier(0.16, 1, 0.3, 1)'
            }}
            title={`Deterministic Matched: ${detRate.toFixed(1)}%`}
          />
          <div
            style={{
              width: `${aiRate}%`,
              background: 'linear-gradient(90deg, #8b5cf6, #a78bfa)',
              transition: 'width 0.8s cubic-bezier(0.16, 1, 0.3, 1)'
            }}
            title={`AI Resolved: ${aiRate.toFixed(1)}%`}
          />
          <div
            style={{
              width: `${unresRate}%`,
              background: 'linear-gradient(90deg, #ef4444, #f87171)',
              transition: 'width 0.8s cubic-bezier(0.16, 1, 0.3, 1)'
            }}
            title={`Unresolved: ${unresRate.toFixed(1)}%`}
          />
        </div>
      </div>

      {/* Metrics Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px' }}>
        
        {/* Metric 1: Deterministic */}
        <div style={{
          padding: '16px',
          background: 'var(--bg-inset)',
          borderRadius: 'var(--radius-md)',
          border: '1px solid rgba(16, 185, 129, 0.2)'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
            <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)' }}>DETERMINISTIC MATCH</span>
            <CheckCircle size={16} color="var(--accent-green)" />
          </div>
          <div style={{ fontSize: '24px', fontWeight: 800, color: '#34d399' }}>
            {summary.match_rate_deterministic_pct !== null ? `${summary.match_rate_deterministic_pct.toFixed(1)}%` : '--'}
          </div>
          <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '2px' }}>
            {summary.matched_deterministic_count} of {summary.total_records} records
          </div>
        </div>

        {/* Metric 2: AI Resolved */}
        <div style={{
          padding: '16px',
          background: 'var(--bg-inset)',
          borderRadius: 'var(--radius-md)',
          border: '1px solid rgba(139, 92, 246, 0.2)'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
            <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)' }}>AI RESOLVED</span>
            <Brain size={16} color="var(--accent-purple)" />
          </div>
          <div style={{ fontSize: '24px', fontWeight: 800, color: '#a78bfa' }}>
            {summary.match_rate_ai_resolved_pct !== null ? `${summary.match_rate_ai_resolved_pct.toFixed(1)}%` : (summary.status === 'matching_complete' ? 'Pending AI' : '--')}
          </div>
          <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '2px' }}>
            {summary.matched_ai_resolved_count} records explained
          </div>
        </div>

        {/* Metric 3: Unresolved Exceptions */}
        <div style={{
          padding: '16px',
          background: 'var(--bg-inset)',
          borderRadius: 'var(--radius-md)',
          border: '1px solid rgba(239, 68, 68, 0.2)'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
            <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)' }}>UNRESOLVED (HONEST)</span>
            <AlertTriangle size={16} color="var(--accent-red)" />
          </div>
          <div style={{ fontSize: '24px', fontWeight: 800, color: '#f87171' }}>
            {summary.total_records ? `${((summary.unresolved_count || 0) / summary.total_records * 100).toFixed(1)}%` : '--'}
          </div>
          <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '2px' }}>
            {summary.unresolved_count} unresolvable records
          </div>
        </div>

        {/* Metric 4: Total Reconciled */}
        <div style={{
          padding: '16px',
          background: 'var(--bg-inset)',
          borderRadius: 'var(--radius-md)',
          border: '1px solid rgba(51, 149, 255, 0.2)'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
            <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)' }}>TOTAL RECONCILED</span>
            <CheckCheck size={16} color="var(--accent-blue)" />
          </div>
          <div style={{ fontSize: '24px', fontWeight: 800, color: '#60a5fa' }}>
            {totalReconciledPct.toFixed(1)}%
          </div>
          <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '2px' }}>
            {summary.matched_deterministic_count + summary.matched_ai_resolved_count} of {summary.total_records} accounted
          </div>
        </div>

      </div>

    </div>
  );
};
