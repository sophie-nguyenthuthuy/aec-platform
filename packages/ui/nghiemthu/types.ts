export type AcceptanceLevel = "cong_viec" | "giai_doan" | "hoan_thanh";

export type AcceptanceStatus =
  | "draft"
  | "in_signoff"
  | "accepted"
  | "rejected"
  | "superseded";

export type SignatoryRole = "cdt" | "tvgs" | "nt" | "tvtk" | "tvqlda";

export type SignatoryDecision =
  | "pending"
  | "approve"
  | "reject"
  | "comment_only";

export type EvidenceKind =
  | "photo"
  | "document"
  | "test_cert"
  | "drawing_ref"
  | "dailylog_ref"
  | "task_ref";

export interface QuantityRow {
  code: string;
  name: string;
  unit: string;
  planned: number;
  actual: number;
  note?: string | null;
}

export interface AcceptanceRecord {
  id: string;
  organization_id: string;
  project_id: string;
  reference_no: string;
  acceptance_level: AcceptanceLevel;
  title: string;
  status: AcceptanceStatus;
  acceptance_date: string;
  location?: string | null;
  work_item_codes: string[];
  quantities: QuantityRow[];
  basis: Record<string, unknown>;
  conclusion?: string | null;
  pdf_file_id?: string | null;
  superseded_by_id?: string | null;
  finalized_at?: string | null;
  created_by?: string | null;
  created_at: string;
  updated_at: string;
}

export interface RecordSummary {
  id: string;
  project_id: string;
  reference_no: string;
  acceptance_level: AcceptanceLevel;
  title: string;
  status: AcceptanceStatus;
  acceptance_date: string;
  signatories_total: number;
  signatories_signed: number;
  mandatory_pending: number;
  finalized_at?: string | null;
  created_at: string;
}

export interface AcceptanceSignatory {
  id: string;
  organization_id: string;
  record_id: string;
  role: SignatoryRole;
  org_name: string;
  representative_name: string;
  position?: string | null;
  required: boolean;
  decision: SignatoryDecision;
  comment?: string | null;
  signed_at?: string | null;
  signature_file_id?: string | null;
  signed_by_user_id?: string | null;
  sort_order: number;
  created_at: string;
}

export interface AcceptanceEvidence {
  id: string;
  organization_id: string;
  record_id: string;
  kind: EvidenceKind;
  file_id?: string | null;
  external_ref?: string | null;
  caption?: string | null;
  captured_at?: string | null;
  sort_order: number;
  created_at: string;
}

export interface AcceptanceDetail extends AcceptanceRecord {
  signatories: AcceptanceSignatory[];
  evidence: AcceptanceEvidence[];
}

export interface FinalizeResult {
  record_id: string;
  status: AcceptanceStatus;
  mandatory_pending_roles: SignatoryRole[];
  rejected_by_roles: SignatoryRole[];
  message: string;
}

export const ACCEPTANCE_LEVEL_LABEL: Record<AcceptanceLevel, string> = {
  cong_viec: "Nghiệm thu công việc",
  giai_doan: "Nghiệm thu giai đoạn",
  hoan_thanh: "Nghiệm thu hoàn thành",
};

export const ACCEPTANCE_STATUS_LABEL: Record<AcceptanceStatus, string> = {
  draft: "Bản nháp",
  in_signoff: "Đang ký",
  accepted: "Đã chấp thuận",
  rejected: "Bị từ chối",
  superseded: "Đã thay thế",
};

export const SIGNATORY_ROLE_LABEL: Record<SignatoryRole, string> = {
  cdt: "Chủ đầu tư (CĐT)",
  tvgs: "Tư vấn giám sát (TVGS)",
  nt: "Nhà thầu (NT)",
  tvtk: "Tư vấn thiết kế (TVTK)",
  tvqlda: "Tư vấn QLDA",
};

export const SIGNATORY_DECISION_LABEL: Record<SignatoryDecision, string> = {
  pending: "Chờ ký",
  approve: "Đồng ý",
  reject: "Từ chối",
  comment_only: "Có ý kiến",
};
