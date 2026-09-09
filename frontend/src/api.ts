import type { BatchSummary, ExceptionItem, AuditLogItem, AccuracyReport } from './types';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export async function uploadBatch(
  settlementFile: File,
  ledgerFile: File,
  timestampToleranceSeconds: number = 2
): Promise<{ batch_id: string; total_records: number; ingestion_error_count: number; status: string }> {
  const formData = new FormData();
  formData.append('settlement_file', settlementFile);
  formData.append('ledger_file', ledgerFile);
  formData.append('timestamp_tolerance_seconds', timestampToleranceSeconds.toString());

  const res = await fetch(`${API_BASE_URL}/batches/upload`, {
    method: 'POST',
    body: formData,
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || 'Failed to upload batch files');
  }

  return res.json();
}

export async function runMatching(batchId: string): Promise<{
  batch_id: string;
  status: string;
  matched_deterministic_count: number;
  exception_count: number;
  match_rate_deterministic_pct: number;
}> {
  const res = await fetch(`${API_BASE_URL}/batches/${batchId}/run-matching`, {
    method: 'POST',
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || 'Failed to run matching engine');
  }

  return res.json();
}

export async function runReasoning(batchId: string): Promise<{
  batch_id: string;
  job_id: string;
  exception_count: number;
  message: string;
}> {
  const res = await fetch(`${API_BASE_URL}/batches/${batchId}/run-reasoning`, {
    method: 'POST',
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || 'Failed to trigger reasoning job');
  }

  return res.json();
}

export async function getBatchSummary(batchId: string): Promise<BatchSummary> {
  const res = await fetch(`${API_BASE_URL}/batches/${batchId}/summary`);
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || 'Failed to fetch batch summary');
  }
  return res.json();
}

export async function getExceptions(
  batchId: string,
  limit: number = 50,
  offset: number = 0,
  status?: string
): Promise<{ total: number; items: ExceptionItem[] }> {
  let url = `${API_BASE_URL}/batches/${batchId}/exceptions?limit=${limit}&offset=${offset}`;
  if (status) {
    url += `&status=${status}`;
  }
  const res = await fetch(url);
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || 'Failed to fetch exceptions list');
  }
  return res.json();
}

export async function approveCard(
  resultId: string,
  reviewedBy: string = 'controller_accountant'
): Promise<{ result_id: string; status: string; journal_posted: boolean; reviewed_at: string }> {
  const res = await fetch(`${API_BASE_URL}/reconciliation/${resultId}/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reviewed_by: reviewedBy }),
  });

  if (res.status === 409) {
    throw new Error('ALREADY_ACTIONED: This record has already been approved/rejected.');
  }

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || 'Failed to approve reasoning card');
  }

  return res.json();
}

export async function rejectCard(
  resultId: string,
  reviewedBy: string = 'controller_accountant',
  overrideNote?: string
): Promise<{ result_id: string; status: string; reviewed_at: string }> {
  const res = await fetch(`${API_BASE_URL}/reconciliation/${resultId}/reject`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reviewed_by: reviewedBy, override_note: overrideNote }),
  });

  if (res.status === 409) {
    throw new Error('ALREADY_ACTIONED: This record has already been actioned.');
  }

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || 'Failed to reject reasoning card');
  }

  return res.json();
}

export async function getAuditLog(
  batchId: string,
  eventType?: string
): Promise<{ total: number; events: AuditLogItem[] }> {
  let url = `${API_BASE_URL}/batches/${batchId}/audit-log`;
  if (eventType) {
    url += `?event_type=${eventType}`;
  }
  const res = await fetch(url);
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || 'Failed to fetch audit log');
  }
  return res.json();
}

export async function getAccuracyReport(batchId: string): Promise<AccuracyReport> {
  const res = await fetch(`${API_BASE_URL}/batches/${batchId}/accuracy-report`);
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || 'Failed to fetch accuracy report');
  }
  return res.json();
}

export async function checkBackendHealth(): Promise<{ status: string; app: string; database: string }> {
  const res = await fetch(`${API_BASE_URL}/health`);
  if (!res.ok) {
    throw new Error('Backend unreachable');
  }
  return res.json();
}
