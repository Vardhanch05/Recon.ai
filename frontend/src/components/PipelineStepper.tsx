import React from 'react';
import { Upload, GitMerge, Brain, CheckCircle2, Clock, Play } from 'lucide-react';
import type { BatchStatus } from '../types';

interface PipelineStepperProps {
  status: BatchStatus | null;
  onRunMatching: () => void;
  onRunReasoning: () => void;
  isMatching: boolean;
  isReasoning: boolean;
  unresolvedCount: number;
}

export const PipelineStepper: React.FC<PipelineStepperProps> = ({
  status,
  onRunMatching,
  onRunReasoning,
  isMatching,
  isReasoning,
  unresolvedCount,
}) => {
  const isUploaded = status === 'uploaded' || status === 'matching_complete' || status === 'reasoning_complete';
  const isMatchingComplete = status === 'matching_complete' || status === 'reasoning_complete';
  const isReasoningComplete = status === 'reasoning_complete';

  return (
    <div className="glass-card" style={{ padding: '20px 24px', marginBottom: '28px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '16px', flexWrap: 'wrap' }}>
        
        {/* Step 1: Upload */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', opacity: isUploaded ? 1 : 0.4 }}>
          <div style={{
            width: '36px',
            height: '36px',
            borderRadius: '50%',
            background: isUploaded ? 'rgba(51, 149, 255, 0.2)' : 'var(--bg-card-subtle)',
            border: `2px solid ${isUploaded ? 'var(--accent-blue)' : 'var(--border-subtle)'}`,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: isUploaded ? 'var(--accent-blue)' : 'var(--text-muted)'
          }}>
            {isUploaded ? <CheckCircle2 size={18} /> : <Upload size={18} />}
          </div>
          <div>
            <div style={{ fontSize: '13px', fontWeight: 600 }}>1. CSV Ingestion</div>
            <div style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>
              {isUploaded ? 'Files Parsed & Stored' : 'Pending Upload'}
            </div>
          </div>
        </div>

        <div style={{ flex: 1, height: '2px', background: isMatchingComplete ? 'var(--accent-blue)' : 'var(--border-subtle)', minWidth: '30px' }} />

        {/* Step 2: Deterministic Matching */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', opacity: status ? 1 : 0.4 }}>
          <div style={{
            width: '36px',
            height: '36px',
            borderRadius: '50%',
            background: isMatchingComplete ? 'rgba(16, 185, 129, 0.2)' : 'var(--bg-card-subtle)',
            border: `2px solid ${isMatchingComplete ? 'var(--accent-green)' : isMatching ? 'var(--accent-blue)' : 'var(--border-subtle)'}`,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: isMatchingComplete ? 'var(--accent-green)' : 'var(--text-muted)'
          }}>
            {isMatchingComplete ? <CheckCircle2 size={18} /> : <GitMerge size={18} />}
          </div>
          <div>
            <div style={{ fontSize: '13px', fontWeight: 600 }}>2. Deterministic Matching</div>
            <div style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>
              {isMatchingComplete ? '80% Matched via Rules' : isMatching ? 'Running Rules...' : 'Ready to Match'}
            </div>
          </div>
          {status === 'uploaded' && (
            <button
              onClick={onRunMatching}
              disabled={isMatching}
              className="btn btn-primary"
              style={{ padding: '6px 14px', fontSize: '12px', marginLeft: '6px' }}
            >
              <Play size={13} />
              <span>{isMatching ? 'Matching...' : 'Run Matching'}</span>
            </button>
          )}
        </div>

        <div style={{ flex: 1, height: '2px', background: isReasoningComplete ? 'var(--accent-purple)' : 'var(--border-subtle)', minWidth: '30px' }} />

        {/* Step 3: LLM Reasoner */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', opacity: isMatchingComplete ? 1 : 0.4 }}>
          <div style={{
            width: '36px',
            height: '36px',
            borderRadius: '50%',
            background: isReasoningComplete ? 'rgba(139, 92, 246, 0.2)' : 'var(--bg-card-subtle)',
            border: `2px solid ${isReasoningComplete ? 'var(--accent-purple)' : isReasoning ? 'var(--accent-amber)' : 'var(--border-subtle)'}`,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: isReasoningComplete ? 'var(--accent-purple)' : 'var(--text-muted)'
          }}>
            {isReasoningComplete ? <CheckCircle2 size={18} /> : isReasoning ? <Clock size={18} className="animate-spin" /> : <Brain size={18} />}
          </div>
          <div>
            <div style={{ fontSize: '13px', fontWeight: 600 }}>3. AI Discrepancy Reasoner</div>
            <div style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>
              {isReasoningComplete ? 'Reasoning Cards Generated' : isReasoning ? 'Analyzing Exceptions...' : 'Math Isolation Loop'}
            </div>
          </div>
          {status === 'matching_complete' && (
            <button
              onClick={onRunReasoning}
              disabled={isReasoning}
              className="btn"
              style={{
                padding: '6px 14px',
                fontSize: '12px',
                marginLeft: '6px',
                background: 'linear-gradient(135deg, #8b5cf6 0%, #6d28d9 100%)',
                color: 'white',
                boxShadow: '0 4px 14px rgba(139, 92, 246, 0.4)'
              }}
            >
              <Brain size={14} />
              <span>{isReasoning ? 'Analyzing...' : 'Run AI Reasoning'}</span>
            </button>
          )}
        </div>

        <div style={{ flex: 1, height: '2px', background: isReasoningComplete ? 'var(--accent-green)' : 'var(--border-subtle)', minWidth: '30px' }} />

        {/* Step 4: Human Review */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', opacity: isReasoningComplete ? 1 : 0.4 }}>
          <div style={{
            width: '36px',
            height: '36px',
            borderRadius: '50%',
            background: isReasoningComplete ? 'rgba(16, 185, 129, 0.15)' : 'var(--bg-card-subtle)',
            border: `2px solid ${isReasoningComplete ? 'var(--accent-green)' : 'var(--border-subtle)'}`,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: isReasoningComplete ? 'var(--accent-green)' : 'var(--text-muted)'
          }}>
            <CheckCircle2 size={18} />
          </div>
          <div>
            <div style={{ fontSize: '13px', fontWeight: 600 }}>4. Human-in-the-Loop</div>
            <div style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>
              {isReasoningComplete ? `${unresolvedCount} Pending Review` : 'Hard-Gate Approval'}
            </div>
          </div>
        </div>

      </div>
    </div>
  );
};
