export type BatchStatus = 'uploaded' | 'matching_complete' | 'reasoning_complete' | 'failed';

export type ReconciliationStatus =
  | 'matched_deterministic'
  | 'matched_ai_resolved'
  | 'exception_unresolved'
  | 'human_approved'
  | 'human_rejected';

export type SuggestedCategory =
  | 'MDR_VARIANCE'
  | 'PARTIAL_REFUND'
  | 'FX_ROUNDING'
  | 'UNRESOLVED';

export interface BatchSummary {
  batch_id: string;
  status: BatchStatus;
  total_records: number;
  matched_deterministic_count: number;
  matched_ai_resolved_count: number;
  unresolved_count: number;
  ingestion_error_count: number;
  match_rate_deterministic_pct: number | null;
  match_rate_ai_resolved_pct: number | null;
  throughput_ms: number | null;
}

export interface CalculationBreakdown {
  billed_amount?: number;
  fee_pct_tested?: number;
  gst_on_fee_pct_tested?: number;
  flat_surcharge_tested?: number;
  refund_amount_tested?: number;
  fx_adjustment_tested?: number;
  expected_settlement?: number;
  actual_settlement?: number;
  residual_gap: number;
  attempts_tried?: string[];
}

export interface ReasoningCardData {
  id: string;
  hypothesis_text: string;
  calculation_breakdown: CalculationBreakdown;
  confidence_score: number;
  suggested_category: SuggestedCategory;
  requires_human_review: boolean;
  human_override_note?: string;
}

export interface SettlementRecord {
  gateway_txn_id: string;
  order_id?: string;
  settled_amount: number;
  settlement_timestamp: string;
  fee_deducted?: number;
  currency: string;
}

export interface OrderLedger {
  order_id: string;
  billed_amount: number;
  order_timestamp: string;
  refund_amount?: number;
  is_international: boolean;
  payment_method?: string;
}

export interface ExceptionItem {
  reconciliation_result_id: string;
  settlement_record: SettlementRecord;
  candidate_orders?: OrderLedger[];
  discrepancy_amount?: number;
  routing_reason?: string;
  status: ReconciliationStatus;
  reasoning_card?: ReasoningCardData;
}

export interface AuditLogItem {
  id: string;
  batch_id: string;
  event_type: 'ingestion_error' | 'match' | 'llm_call' | 'human_approval' | 'human_rejection' | 'journal_posted';
  actor: string;
  payload_json: Record<string, any>;
  timestamp: string;
}

export interface AccuracyReport {
  total_evaluated: number;
  explainable_total: number;
  explainable_correct: number;
  explainable_accuracy_pct: number;
  unresolvable_total: number;
  unresolvable_correct: number;
  unresolvable_accuracy_pct: number;
  overall_accuracy_pct: number;
  confusion_matrix: {
    true_positives_explainable: number;
    true_negatives_unresolvable: number;
    false_positives: number;
    false_negatives: number;
    category_breakdown: Record<string, { total: number; correct: number }>;
  };
}
