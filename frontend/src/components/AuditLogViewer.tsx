import React, { useState } from 'react';
import { History, CheckCircle, Brain, UserCheck, AlertCircle, FileCheck } from 'lucide-react';
import type { AuditLogItem } from '../types';

interface AuditLogViewerProps {
  events: AuditLogItem[];
  isLoading: boolean;
}

export const AuditLogViewer: React.FC<AuditLogViewerProps> = ({ events, isLoading }) => {
  const [selectedEvent, setSelectedEvent] = useState<AuditLogItem | null>(null);
  const [eventFilter, setEventFilter] = useState<string>('ALL');

  const filteredEvents = events.filter((e) => {
    if (eventFilter === 'ALL') return true;
    return e.event_type === eventFilter;
  });

  const getEventBadge = (type: string) => {
    switch (type) {
      case 'match':
        return <span className="badge badge-green"><CheckCircle size={12} /> Deterministic Match</span>;
      case 'llm_call':
        return <span className="badge badge-purple"><Brain size={12} /> LLM Reasoner</span>;
      case 'human_approval':
        return <span className="badge badge-blue"><UserCheck size={12} /> Human Approval</span>;
      case 'human_rejection':
        return <span className="badge badge-red"><AlertCircle size={12} /> Human Rejection</span>;
      case 'journal_posted':
        return <span className="badge badge-green"><FileCheck size={12} /> Journal Posted</span>;
      case 'ingestion_error':
        return <span className="badge badge-amber"><AlertCircle size={12} /> Ingestion Error</span>;
      default:
        return <span className="badge badge-blue">{type}</span>;
    }
  };

  return (
    <div className="glass-card" style={{ padding: '28px', marginBottom: '32px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '20px', flexWrap: 'wrap', gap: '12px' }}>
        <div>
          <h2 style={{ fontSize: '18px', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '8px' }}>
            <History size={20} color="var(--accent-blue)" />
            Immutable Audit Trail ({events.length} Events)
          </h2>
          <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '2px' }}>
            Append-only chronological log of every ingestion, deterministic match, tool call, and accountant decision.
          </p>
        </div>

        {/* Filter Tabs */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
          {['ALL', 'match', 'llm_call', 'human_approval', 'human_rejection', 'journal_posted'].map((type) => (
            <button
              key={type}
              onClick={() => setEventFilter(type)}
              className={`btn ${eventFilter === type ? 'btn-primary' : 'btn-secondary'}`}
              style={{ padding: '4px 10px', fontSize: '11px', textTransform: 'uppercase' }}
            >
              {type.replace('_', ' ')}
            </button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <div style={{ padding: '32px', textAlign: 'center', color: 'var(--text-secondary)' }}>Loading audit events...</div>
      ) : filteredEvents.length === 0 ? (
        <div style={{ padding: '32px', textAlign: 'center', color: 'var(--text-muted)' }}>No audit events logged yet.</div>
      ) : (
        <div style={{ maxHeight: '420px', overflowY: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border-subtle)', color: 'var(--text-muted)', textAlign: 'left' }}>
                <th style={{ padding: '10px 8px' }}>Timestamp</th>
                <th style={{ padding: '10px 8px' }}>Actor</th>
                <th style={{ padding: '10px 8px' }}>Event Type</th>
                <th style={{ padding: '10px 8px' }}>Payload Summary</th>
                <th style={{ padding: '10px 8px', textAlign: 'right' }}>Details</th>
              </tr>
            </thead>
            <tbody>
              {filteredEvents.map((e) => (
                <tr
                  key={e.id}
                  style={{ borderBottom: '1px solid var(--border-subtle)', transition: 'background 0.15s ease' }}
                  onMouseEnter={(el) => (el.currentTarget.style.background = 'var(--bg-inset)')}
                  onMouseLeave={(el) => (el.currentTarget.style.background = 'transparent')}
                >
                  <td style={{ padding: '10px 8px', color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>
                    {new Date(e.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                  </td>
                  <td style={{ padding: '10px 8px', fontWeight: 600 }}>{e.actor}</td>
                  <td style={{ padding: '10px 8px' }}>{getEventBadge(e.event_type)}</td>
                  <td style={{ padding: '10px 8px', color: 'var(--text-secondary)', maxWidth: '300px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {JSON.stringify(e.payload_json)}
                  </td>
                  <td style={{ padding: '10px 8px', textAlign: 'right' }}>
                    <button
                      onClick={() => setSelectedEvent(e)}
                      className="btn btn-secondary"
                      style={{ padding: '4px 10px', fontSize: '11px' }}
                    >
                      Inspect JSON
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Payload Inspection Modal */}
      {selectedEvent && (
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
          <div className="glass-card" style={{ maxWidth: '560px', width: '100%', padding: '24px', background: 'var(--bg-card)' }}>
            <h3 style={{ fontSize: '16px', fontWeight: 700, marginBottom: '8px' }}>
              Audit Event Payload Inspector
            </h3>
            <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '14px' }}>
              ID: {selectedEvent.id} | Timestamp: {selectedEvent.timestamp}
            </div>
            
            <pre style={{
              background: 'var(--bg-inset)',
              padding: '14px',
              borderRadius: 'var(--radius-md)',
              border: '1px solid var(--border-subtle)',
              fontSize: '12px',
              color: '#38bdf8',
              maxHeight: '300px',
              overflowY: 'auto'
            }}>
              {JSON.stringify(selectedEvent.payload_json, null, 2)}
            </pre>

            <div style={{ marginTop: '20px', textAlign: 'right' }}>
              <button
                onClick={() => setSelectedEvent(null)}
                className="btn btn-primary"
                style={{ padding: '8px 18px' }}
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
