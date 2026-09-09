import React from 'react';
import { ShieldCheck, Award, RefreshCw } from 'lucide-react';

interface HeaderProps {
  backendConnected: boolean;
  onOpenAccuracy: () => void;
  onRefresh: () => void;
  activeBatchId: string | null;
}

export const Header: React.FC<HeaderProps> = ({
  backendConnected,
  onOpenAccuracy,
  onRefresh,
  activeBatchId,
}) => {
  return (
    <header style={{
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      padding: '16px 0 28px 0',
      borderBottom: '1px solid var(--border-subtle)',
      marginBottom: '32px'
    }}>
      {/* Brand Title */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
        <div style={{
          width: '44px',
          height: '44px',
          borderRadius: '12px',
          background: 'linear-gradient(135deg, #3395ff 0%, #7c3aed 100%)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          boxShadow: '0 0 20px rgba(51, 149, 255, 0.4)'
        }}>
          <ShieldCheck size={26} color="#ffffff" />
        </div>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <h1 style={{ fontSize: '24px', fontWeight: 800, letterSpacing: '-0.02em', background: 'linear-gradient(90deg, #ffffff, #94a3b8)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
              Recon.ai
            </h1>
            <span className="badge badge-blue" style={{ fontSize: '11px', padding: '2px 8px' }}>
              AI Finance Controller
            </span>
          </div>
          <p style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
            Multi-Source Settlement Reconciler & Discrepancy Reasoner
          </p>
        </div>
      </div>

      {/* Action Controls & Indicators */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
        {/* Backend Status */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          padding: '6px 12px',
          borderRadius: '20px',
          background: 'var(--bg-card-subtle)',
          border: '1px solid var(--border-subtle)',
          fontSize: '12px',
          color: backendConnected ? '#34d399' : '#f87171'
        }}>
          <div style={{
            width: '8px',
            height: '8px',
            borderRadius: '50%',
            background: backendConnected ? '#10b981' : '#ef4444',
            boxShadow: backendConnected ? '0 0 8px #10b981' : 'none'
          }} />
          <span>{backendConnected ? 'Backend Live' : 'Backend Disconnected'}</span>
        </div>

        {/* Live Accuracy Report Button */}
        <button
          onClick={onOpenAccuracy}
          disabled={!activeBatchId}
          className="btn btn-secondary"
          style={{
            borderColor: 'rgba(139, 92, 246, 0.4)',
            background: 'rgba(139, 92, 246, 0.08)',
            color: '#c4b5fd'
          }}
          title="Verify reasoner output against ground_truth.csv answer key"
        >
          <Award size={16} />
          <span>Accuracy Report</span>
        </button>

        {/* Refresh Summary Button */}
        {activeBatchId && (
          <button
            onClick={onRefresh}
            className="btn btn-secondary"
            style={{ padding: '8px 12px' }}
            title="Refresh Batch Data"
          >
            <RefreshCw size={15} />
          </button>
        )}
      </div>
    </header>
  );
};
