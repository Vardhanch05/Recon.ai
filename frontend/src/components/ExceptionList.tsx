import React, { useState } from 'react';
import { Search, Inbox, CheckCircle } from 'lucide-react';
import type { ExceptionItem } from '../types';
import { ReasoningCard } from './ReasoningCard';

interface ExceptionListProps {
  items: ExceptionItem[];
  onApprove: (id: string) => Promise<void>;
  onReject: (id: string, note?: string) => Promise<void>;
  isLoading: boolean;
}

export const ExceptionList: React.FC<ExceptionListProps> = ({ items, onApprove, onReject, isLoading }) => {
  const [filterTab, setFilterTab] = useState<'ALL' | 'RESOLVED' | 'UNRESOLVED' | 'APPROVED' | 'REJECTED'>('ALL');
  const [searchQuery, setSearchQuery] = useState('');

  const filteredItems = items.filter((item) => {
    // 1. Tab Filter
    if (filterTab === 'RESOLVED') {
      if (item.status !== 'matched_ai_resolved') return false;
    } else if (filterTab === 'UNRESOLVED') {
      if (item.status !== 'exception_unresolved') return false;
    } else if (filterTab === 'APPROVED') {
      if (item.status !== 'human_approved') return false;
    } else if (filterTab === 'REJECTED') {
      if (item.status !== 'human_rejected') return false;
    }

    // 2. Search Filter
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      const matchTxn = item.settlement_record.gateway_txn_id.toLowerCase().includes(q);
      const matchOrder = item.settlement_record.order_id?.toLowerCase().includes(q);
      const matchHypo = item.reasoning_card?.hypothesis_text.toLowerCase().includes(q);
      const matchCat = item.reasoning_card?.suggested_category.toLowerCase().includes(q);
      return matchTxn || matchOrder || matchHypo || matchCat;
    }

    return true;
  });

  const resolvedCount = items.filter((i) => i.status === 'matched_ai_resolved').length;
  const unresolvedCount = items.filter((i) => i.status === 'exception_unresolved').length;
  const approvedCount = items.filter((i) => i.status === 'human_approved').length;
  const rejectedCount = items.filter((i) => i.status === 'human_rejected').length;

  return (
    <div style={{ marginBottom: '40px' }}>
      
      {/* Title & Filter bar */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '16px', flexWrap: 'wrap', marginBottom: '20px' }}>
        <div>
          <h2 style={{ fontSize: '18px', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Inbox size={20} color="var(--accent-purple)" />
            Exception Review Queue ({items.length})
          </h2>
          <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '2px' }}>
            Review AI reasoning cards, verify arithmetic breakdowns, and approve journal entries.
          </p>
        </div>

        {/* Search Box */}
        <div style={{ position: 'relative', width: '260px' }}>
          <Search size={15} style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
          <input
            type="text"
            placeholder="Search txn, order, hypothesis..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            style={{
              width: '100%',
              padding: '8px 12px 8px 36px',
              background: 'var(--bg-card)',
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-md)',
              color: 'var(--text-primary)',
              fontSize: '13px'
            }}
          />
        </div>
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '20px', flexWrap: 'wrap' }}>
        <button
          onClick={() => setFilterTab('ALL')}
          className={`btn ${filterTab === 'ALL' ? 'btn-primary' : 'btn-secondary'}`}
          style={{ padding: '6px 14px', fontSize: '12px' }}
        >
          All ({items.length})
        </button>
        <button
          onClick={() => setFilterTab('RESOLVED')}
          className={`btn ${filterTab === 'RESOLVED' ? 'btn-primary' : 'btn-secondary'}`}
          style={{ padding: '6px 14px', fontSize: '12px', borderColor: filterTab === 'RESOLVED' ? undefined : 'rgba(139, 92, 246, 0.3)' }}
        >
          AI Resolved ({resolvedCount})
        </button>
        <button
          onClick={() => setFilterTab('UNRESOLVED')}
          className={`btn ${filterTab === 'UNRESOLVED' ? 'btn-primary' : 'btn-secondary'}`}
          style={{ padding: '6px 14px', fontSize: '12px', borderColor: filterTab === 'UNRESOLVED' ? undefined : 'rgba(239, 68, 68, 0.3)' }}
        >
          Unresolved ({unresolvedCount})
        </button>
        <button
          onClick={() => setFilterTab('APPROVED')}
          className={`btn ${filterTab === 'APPROVED' ? 'btn-primary' : 'btn-secondary'}`}
          style={{ padding: '6px 14px', fontSize: '12px', borderColor: filterTab === 'APPROVED' ? undefined : 'rgba(16, 185, 129, 0.3)' }}
        >
          Approved ({approvedCount})
        </button>
        <button
          onClick={() => setFilterTab('REJECTED')}
          className={`btn ${filterTab === 'REJECTED' ? 'btn-primary' : 'btn-secondary'}`}
          style={{ padding: '6px 14px', fontSize: '12px' }}
        >
          Rejected ({rejectedCount})
        </button>
      </div>

      {/* List content */}
      {isLoading ? (
        <div className="glass-card" style={{ padding: '40px', textAlign: 'center', color: 'var(--text-secondary)' }}>
          Loading exception records...
        </div>
      ) : filteredItems.length === 0 ? (
        <div className="glass-card" style={{ padding: '48px', textAlign: 'center', color: 'var(--text-muted)' }}>
          <CheckCircle size={32} color="var(--accent-green)" style={{ margin: '0 auto 12px auto' }} />
          <div style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text-primary)' }}>No exceptions found</div>
          <div style={{ fontSize: '13px', marginTop: '4px' }}>All transactions in this view have been processed.</div>
        </div>
      ) : (
        filteredItems.map((item) => (
          <ReasoningCard
            key={item.reconciliation_result_id}
            item={item}
            onApprove={onApprove}
            onReject={onReject}
          />
        ))
      )}
    </div>
  );
};
