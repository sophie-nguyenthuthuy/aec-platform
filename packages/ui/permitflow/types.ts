export type ProjectClassification =
  | "cap_iv"
  | "cap_iii"
  | "cap_ii"
  | "cap_i"
  | "dac_biet";

export type InvestmentType = "domestic" | "fdi";

export type DossierStatus =
  | "planning"
  | "in_progress"
  | "on_hold"
  | "completed"
  | "cancelled";

export type StageCode =
  | "chu_truong_dau_tu"
  | "quy_hoach_1_500"
  | "tham_dinh_tkcs"
  | "gpxd"
  | "nghiem_thu_pccc";

export const STAGE_ORDER: StageCode[] = [
  "chu_truong_dau_tu",
  "quy_hoach_1_500",
  "tham_dinh_tkcs",
  "gpxd",
  "nghiem_thu_pccc",
];

export type Authority =
  | "BKHDT"
  | "BXD"
  | "UBND_TINH"
  | "UBND_HUYEN"
  | "SXD"
  | "PC07";

export type StageStatus =
  | "not_started"
  | "preparing"
  | "submitted"
  | "in_review"
  | "rfi"
  | "approved"
  | "rejected"
  | "withdrawn"
  | "expired";

export type SubmissionType =
  | "initial"
  | "rfi_response"
  | "resubmission"
  | "withdrawal_request";

export type SubmissionOutcome =
  | "pending"
  | "accepted"
  | "rfi_issued"
  | "rejected";

export interface PermitDossier {
  id: string;
  organization_id: string;
  project_id: string;
  name: string;
  classification: ProjectClassification;
  investment_type: InvestmentType;
  status: DossierStatus;
  location: Record<string, unknown>;
  land_cert_file_id?: string | null;
  land_parcel_no?: string | null;
  notes?: string | null;
  created_by?: string | null;
  created_at: string;
  updated_at: string;
}

export interface DossierSummary {
  id: string;
  project_id: string;
  name: string;
  classification: ProjectClassification;
  investment_type: InvestmentType;
  status: DossierStatus;
  stages_total: number;
  stages_approved: number;
  next_stage_code?: StageCode | null;
  next_stage_status?: StageStatus | null;
  nearest_expiry?: string | null;
  created_at: string;
}

export interface PermitSubmission {
  id: string;
  organization_id: string;
  stage_id: string;
  round_number: number;
  submission_type: SubmissionType;
  submitted_at: string;
  submitted_by?: string | null;
  receipt_number?: string | null;
  package_file_ids: string[];
  outcome?: string | null;
  outcome_status: SubmissionOutcome;
  outcome_at?: string | null;
  created_at: string;
}

export interface PermitStage {
  id: string;
  organization_id: string;
  dossier_id: string;
  stage_code: StageCode;
  sequence: number;
  authority: Authority;
  status: StageStatus;
  legal_basis: string[];
  target_submit_date?: string | null;
  submitted_date?: string | null;
  decision_date?: string | null;
  decision_number?: string | null;
  decision_file_id?: string | null;
  expiry_date?: string | null;
  notes?: string | null;
  created_at: string;
  updated_at: string;
}

export interface StageWithSubmissions extends PermitStage {
  submissions: PermitSubmission[];
}

export interface DossierDetail extends PermitDossier {
  stages: StageWithSubmissions[];
}

export interface PermitAlert {
  dossier_id: string;
  project_id: string;
  stage_id: string;
  stage_code: StageCode;
  code: "expiring_soon" | "overdue_submission" | "stalled_review";
  severity: "info" | "warning" | "critical";
  message: string;
  expiry_date?: string | null;
  days_until?: number | null;
}

// Vietnamese display labels — mapped at the UI boundary so the API
// stays English-codes-only.

export const CLASSIFICATION_LABEL: Record<ProjectClassification, string> = {
  cap_iv: "Cấp IV",
  cap_iii: "Cấp III",
  cap_ii: "Cấp II",
  cap_i: "Cấp I",
  dac_biet: "Đặc biệt",
};

export const INVESTMENT_TYPE_LABEL: Record<InvestmentType, string> = {
  domestic: "Trong nước",
  fdi: "FDI",
};

export const DOSSIER_STATUS_LABEL: Record<DossierStatus, string> = {
  planning: "Lập kế hoạch",
  in_progress: "Đang xử lý",
  on_hold: "Tạm dừng",
  completed: "Hoàn thành",
  cancelled: "Đã huỷ",
};

export const STAGE_CODE_LABEL: Record<StageCode, string> = {
  chu_truong_dau_tu: "Chủ trương đầu tư",
  quy_hoach_1_500: "Quy hoạch 1/500",
  tham_dinh_tkcs: "Thẩm định TKCS",
  gpxd: "Giấy phép xây dựng (GPXD)",
  nghiem_thu_pccc: "Nghiệm thu PCCC",
};

export const STAGE_STATUS_LABEL: Record<StageStatus, string> = {
  not_started: "Chưa bắt đầu",
  preparing: "Chuẩn bị hồ sơ",
  submitted: "Đã nộp",
  in_review: "Đang thẩm định",
  rfi: "Yêu cầu bổ sung",
  approved: "Đã chấp thuận",
  rejected: "Bị từ chối",
  withdrawn: "Rút hồ sơ",
  expired: "Hết hiệu lực",
};

export const AUTHORITY_LABEL: Record<Authority, string> = {
  BKHDT: "Bộ KH&ĐT",
  BXD: "Bộ Xây dựng",
  UBND_TINH: "UBND tỉnh/TP",
  UBND_HUYEN: "UBND huyện/quận",
  SXD: "Sở Xây dựng",
  PC07: "Cảnh sát PCCC",
};
