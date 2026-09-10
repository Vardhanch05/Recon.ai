import React, { useState, useEffect } from 'react';
import { Header } from './components/Header';
import { PipelineStepper } from './components/PipelineStepper';
import { UploadPanel } from './components/UploadPanel';
import { MatchRateSummaryCard } from './components/MatchRateSummaryCard';
import { ExceptionList } from './components/ExceptionList';
import { AuditLogViewer } from './components/AuditLogViewer';
import { AccuracyReportModal } from './components/AccuracyReportModal';
import {
  uploadBatch,
  runMatching,
  runReasoning,
  getBatchSummary,
  getExceptions,
  approveCard,
  rejectCard,
  getAuditLog,
  getAccuracyReport,
  checkBackendHealth
} from './api';
import type { BatchSummary, ExceptionItem, AuditLogItem, AccuracyReport } from './types';
import { Layers, History, AlertCircle } from 'lucide-react';

export const App: React.FC = () => {
  const [backendConnected, setBackendConnected] = useState(false);
  const [activeBatchId, setActiveBatchId] = useState<string | null>(null);
  const [summary, setSummary] = useState<BatchSummary | null>(null);
  const [exceptions, setExceptions] = useState<ExceptionItem[]>([]);
  const [auditLogs, setAuditLogs] = useState<AuditLogItem[]>([]);
  const [accuracyReport, setAccuracyReport] = useState<AccuracyReport | null>(null);

  const [activeTab, setActiveTab] = useState<'RECONCILIATION' | 'AUDIT_LOG'>('RECONCILIATION');
  const [isUploading, setIsUploading] = useState(false);
  const [isMatching, setIsMatching] = useState(false);
  const [isReasoning, setIsReasoning] = useState(false);
  const [isExceptionsLoading, setIsExceptionsLoading] = useState(false);
  const [isAuditLoading, setIsAuditLoading] = useState(false);
  const [showAccuracyModal, setShowAccuracyModal] = useState(false);
  const [accuracyLoading, setAccuracyLoading] = useState(false);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 4000);
  };

  // 1. Initial Health Check
  useEffect(() => {
    const pingBackend = async () => {
      try {
        await checkBackendHealth();
        setBackendConnected(true);
      } catch {
        setBackendConnected(false);
      }
    };
    pingBackend();
    const interval = setInterval(pingBackend, 8000);
    return () => clearInterval(interval);
  }, []);

  // 2. Refresh Batch Summary & Exception Items
  const refreshBatchData = async (batchId: string) => {
    try {
      const sum = await getBatchSummary(batchId);
      setSummary(sum);

      if (sum.status === 'matching_complete' || sum.status === 'reasoning_complete') {
        setIsExceptionsLoading(true);
        const excData = await getExceptions(batchId);
        setExceptions(excData.items);
        setIsExceptionsLoading(false);
      }

      const logsData = await getAuditLog(batchId);
      setAuditLogs(logsData.events);
    } catch (err: any) {
      console.error('Error refreshing batch data:', err);
    }
  };

  // 3. Polling loop during AI reasoning with timeout guard (FIX A12)
  useEffect(() => {
    if (!activeBatchId || !isReasoning) return;

    let pollCount = 0;
    const MAX_POLLS = 150; // 5 minutes max at 2s intervals

    const pollInterval = setInterval(async () => {
      pollCount += 1;
      if (pollCount > MAX_POLLS) {
        setIsReasoning(false);
        showToast('Reasoning operation timed out after 5 minutes. Check backend logs.');
        clearInterval(pollInterval);
        return;
      }

      try {
        const sum = await getBatchSummary(activeBatchId);
        setSummary(sum);

        if (sum.status === 'reasoning_complete' || sum.status === 'failed') {
          setIsReasoning(false);
          refreshBatchData(activeBatchId);
          showToast('AI Discrepancy Reasoning Completed! Reasoning cards ready for review.');
          clearInterval(pollInterval);
        }
      } catch (err) {
        console.error('Error polling summary:', err);
      }
    }, 2000);

    return () => clearInterval(pollInterval);
  }, [activeBatchId, isReasoning]);

  // Handle Upload
  const handleUpload = async (settlementFile: File, ledgerFile: File, tolerance: number) => {
    setIsUploading(true);
    try {
      const result = await uploadBatch(settlementFile, ledgerFile, tolerance);
      setActiveBatchId(result.batch_id);
      await refreshBatchData(result.batch_id);
      showToast(`Batch uploaded successfully! ${result.total_records} records ingested.`);
    } catch (err: any) {
      showToast(`Upload failed: ${err.message}`);
      throw err;
    } finally {
      setIsUploading(false);
    }
  };

  // Handle Run Matching
  const handleRunMatching = async () => {
    if (!activeBatchId) return;
    setIsMatching(true);
    try {
      const result = await runMatching(activeBatchId);
      await refreshBatchData(activeBatchId);
      showToast(`Deterministic match completed: ${result.matched_deterministic_count} matched (${result.match_rate_deterministic_pct}%).`);
    } catch (err: any) {
      showToast(`Matching failed: ${err.message}`);
    } finally {
      setIsMatching(false);
    }
  };

  // Handle Run Reasoning
  const handleRunReasoning = async () => {
    if (!activeBatchId) return;
    setIsReasoning(true);
    try {
      await runReasoning(activeBatchId);
      showToast('AI Reasoning background job started. Polling summary status...');
    } catch (err: any) {
      setIsReasoning(false);
      showToast(`Reasoning start failed: ${err.message}`);
    }
  };

  // Handle Approve Card
  const handleApprove = async (resultId: string) => {
    try {
      await approveCard(resultId);
      showToast('Transaction approved and journal entry posted successfully!');
      if (activeBatchId) refreshBatchData(activeBatchId);
    } catch (err: any) {
      if (err.message?.includes('ALREADY_ACTIONED')) {
        showToast('Notice: This card has already been actioned (409 Conflict).');
      } else {
        showToast(`Approval failed: ${err.message}`);
      }
      if (activeBatchId) refreshBatchData(activeBatchId);
    }
  };

  // Handle Reject Card
  const handleReject = async (resultId: string, note?: string) => {
    try {
      await rejectCard(resultId, 'controller_accountant', note);
      showToast('Transaction rejected and routed to manual review.');
      if (activeBatchId) refreshBatchData(activeBatchId);
    } catch (err: any) {
      if (err.message?.includes('ALREADY_ACTIONED')) {
        showToast('Notice: This card has already been actioned (409 Conflict).');
      } else {
        showToast(`Rejection failed: ${err.message}`);
      }
      if (activeBatchId) refreshBatchData(activeBatchId);
    }
  };

  // Handle Open Accuracy Report
  const handleOpenAccuracy = async () => {
    if (!activeBatchId) return;
    setShowAccuracyModal(true);
    setAccuracyLoading(true);
    try {
      const report = await getAccuracyReport(activeBatchId);
      setAccuracyReport(report);
    } catch (err: any) {
      showToast(`Accuracy report evaluation error: ${err.message}`);
    } finally {
      setAccuracyLoading(false);
    }
  };

  return (
    <div className="app-container">
      {/* Toast Notification */}
      {toastMessage && (
        <div style={{
          position: 'fixed',
          bottom: '24px',
          right: '24px',
          background: 'var(--bg-card)',
          border: '1px solid var(--accent-blue)',
          boxShadow: '0 10px 30px rgba(0, 0, 0, 0.6)',
          borderRadius: 'var(--radius-md)',
          padding: '14px 20px',
          color: 'var(--text-primary)',
          fontSize: '13px',
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
          zIndex: 2000,
          animation: 'fadeIn 0.2s ease'
        }}>
          <AlertCircle size={16} color="var(--accent-blue)" />
          <span>{toastMessage}</span>
        </div>
      )}

      {/* Brand Header */}
      <Header
        backendConnected={backendConnected}
        onOpenAccuracy={handleOpenAccuracy}
        onRefresh={() => activeBatchId && refreshBatchData(activeBatchId)}
        activeBatchId={activeBatchId}
      />

      {/* Pipeline Stepper */}
      <PipelineStepper
        status={summary?.status || null}
        onRunMatching={handleRunMatching}
        onRunReasoning={handleRunReasoning}
        isMatching={isMatching}
        isReasoning={isReasoning}
        unresolvedCount={summary?.unresolved_count || 0}
      />

      {/* Step 1: Upload Panel (Shown if no active batch) */}
      {!summary && (
        <UploadPanel onUpload={handleUpload} isLoading={isUploading} />
      )}

      {/* Step 2+: Batch Active Dashboard */}
      {summary && (
        <>
          <MatchRateSummaryCard summary={summary} />

          {/* Navigation Tabs */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', borderBottom: '1px solid var(--border-subtle)', marginBottom: '28px' }}>
            <button
              onClick={() => setActiveTab('RECONCILIATION')}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                padding: '12px 16px',
                background: 'transparent',
                border: 'none',
                borderBottom: `2px solid ${activeTab === 'RECONCILIATION' ? 'var(--accent-blue)' : 'transparent'}`,
                color: activeTab === 'RECONCILIATION' ? 'var(--text-primary)' : 'var(--text-secondary)',
                fontWeight: 600,
                fontSize: '14px',
                cursor: 'pointer'
              }}
            >
              <Layers size={16} />
              <span>Exception Review Queue ({exceptions.length})</span>
            </button>

            <button
              onClick={() => {
                setActiveTab('AUDIT_LOG');
                if (activeBatchId) {
                  setIsAuditLoading(true);
                  getAuditLog(activeBatchId).then((d) => setAuditLogs(d.events)).finally(() => setIsAuditLoading(false));
                }
              }}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                padding: '12px 16px',
                background: 'transparent',
                border: 'none',
                borderBottom: `2px solid ${activeTab === 'AUDIT_LOG' ? 'var(--accent-blue)' : 'transparent'}`,
                color: activeTab === 'AUDIT_LOG' ? 'var(--text-primary)' : 'var(--text-secondary)',
                fontWeight: 600,
                fontSize: '14px',
                cursor: 'pointer'
              }}
            >
              <History size={16} />
              <span>Immutable Audit Trail ({auditLogs.length})</span>
            </button>
          </div>

          {/* Tab 1: Exceptions & Reasoning Cards */}
          {activeTab === 'RECONCILIATION' && (
            <ExceptionList
              items={exceptions}
              onApprove={handleApprove}
              onReject={handleReject}
              isLoading={isExceptionsLoading}
            />
          )}

          {/* Tab 2: Audit Trail Viewer */}
          {activeTab === 'AUDIT_LOG' && (
            <AuditLogViewer events={auditLogs} isLoading={isAuditLoading} />
          )}
        </>
      )}

      {/* Accuracy Report Modal */}
      {showAccuracyModal && (
        <AccuracyReportModal
          report={accuracyReport}
          onClose={() => setShowAccuracyModal(false)}
          isLoading={accuracyLoading}
        />
      )}
    </div>
  );
};

export default App;
