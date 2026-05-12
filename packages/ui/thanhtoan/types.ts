export type ClaimStatus =
  | "draft"
  | "submitted"
  | "in_review"
  | "approved"
  | "rejected"
  | "paid"
  | "cancelled";

export type PartyDecision = "approve" | "reject";

export type EvidenceKind =
  | "photo"
  | "document"
  | "invoice"
  | "test_cert"
  | "dailylog_ref"
  | "nghiemthu_ref";

export interface PaymentClaim {
  id: string;
  organization_id: string;
  project_id: string;
  claim_no: string;
  sequence: number;
  period_start: string;
  period_end: string;
  status: ClaimStatus;
  subtotal_vnd: number;
  vat_pct: string;
  vat_vnd: number;
  gross_vnd: number;
  retention_pct: string;
  retention_vnd: number;
  tndn_pct: string;
  tndn_vnd: number;
  net_payable_vnd: number;
  cumulative_prev_vnd: number;
  submitted_at?: string | null;
  cdt_signed_at?: string | null;
  cdt_decision?: string | null;
  cdt_comment?: string | null;
  tvgs_signed_at?: string | null;
  tvgs_decision?: string | null;
  tvgs_comment?: string | null;
  approved_at?: string | null;
  rejected_at?: string | null;
  due_at?: string | null;
  paid_at?: string | null;
  payment_reference?: string | null;
  notes?: string | null;
  created_at: string;
  updated_at: string;
}

export interface PaymentClaimLine {
  id: string;
  organization_id: string;
  claim_id: string;
  work_item_code: string;
  description: string;
  unit: string;
  planned_qty: string;
  this_period_qty: string;
  cumulative_qty: string;
  unit_rate_vnd: number;
  this_period_amount_vnd: number;
  cumulative_amount_vnd: number;
  completion_pct?: string | null;
  notes?: string | null;
  evidence_file_ids: string[];
  sort_order: number;
  created_at: string;
  updated_at: string;
}

export interface ClaimSummary {
  id: string;
  project_id: string;
  claim_no: string;
  sequence: number;
  period_start: string;
  period_end: string;
  status: ClaimStatus;
  net_payable_vnd: number;
  line_count: number;
  due_at?: string | null;
  paid_at?: string | null;
  created_at: string;
}

export interface PaymentClaimDetail extends PaymentClaim {
  lines: PaymentClaimLine[];
  evidence: PaymentClaimEvidence[];
}

export interface PaymentClaimEvidence {
  id: string;
  organization_id: string;
  claim_id: string;
  kind: EvidenceKind;
  file_id?: string | null;
  external_ref?: string | null;
  caption?: string | null;
  payload: Record<string, unknown>;
  sort_order: number;
  created_at: string;
}

export interface CumulativeRow {
  work_item_code: string;
  description: string;
  unit: string;
  planned_qty: string;
  cumulative_qty: string;
  cumulative_amount_vnd: number;
  completion_pct?: string | null;
}

export interface CumulativeView {
  claim_id: string;
  project_id: string;
  rows: CumulativeRow[];
  grand_total_vnd: number;
}

export const CLAIM_STATUS_LABEL: Record<ClaimStatus, string> = {
  draft: "Bản nháp",
  submitted: "Đã nộp",
  in_review: "Đang xét duyệt",
  approved: "Đã chấp thuận",
  rejected: "Bị từ chối",
  paid: "Đã thanh toán",
  cancelled: "Đã huỷ",
};

const VND_FMT = new Intl.NumberFormat("vi-VN");

export function formatVnd(amount: number): string {
  return `${VND_FMT.format(amount)} ₫`;
}
