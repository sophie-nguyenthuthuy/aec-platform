export type CertSystem =
  | "lotus_nr"
  | "lotus_homes"
  | "lotus_bio"
  | "lotus_intl"
  | "edge";

export type TargetLevel =
  | "certified"
  | "silver"
  | "gold"
  | "platinum"
  | "edge_certified"
  | "edge_advanced"
  | "edge_zero";

export type CertStatus =
  | "planning"
  | "self_assessment"
  | "submitted"
  | "provisional"
  | "final_cert"
  | "rejected"
  | "expired";

export type CreditCategory =
  | "energy"
  | "water"
  | "materials"
  | "ieq"
  | "site"
  | "operations"
  | "innovation";

export type CreditStatus =
  | "not_attempted"
  | "targeted"
  | "documented"
  | "verified"
  | "rejected";

export interface GreenCertification {
  id: string;
  organization_id: string;
  project_id: string;
  system: CertSystem;
  target_level: TargetLevel;
  achieved_level?: TargetLevel | null;
  status: CertStatus;
  achieved_points: string;
  max_points: string;
  project_brief: Record<string, unknown>;
  certification_no?: string | null;
  awarded_at?: string | null;
  valid_until?: string | null;
  assessor_name?: string | null;
  notes?: string | null;
  created_at: string;
  updated_at: string;
}

export interface CertSummary {
  id: string;
  project_id: string;
  system: CertSystem;
  target_level: TargetLevel;
  achieved_level?: TargetLevel | null;
  status: CertStatus;
  achieved_points: string;
  max_points: string;
  credit_total: number;
  credit_verified: number;
  certification_no?: string | null;
  awarded_at?: string | null;
  valid_until?: string | null;
  created_at: string;
}

export interface GreenCredit {
  id: string;
  organization_id: string;
  certification_id: string;
  code: string;
  category: CreditCategory;
  title: string;
  description?: string | null;
  status: CreditStatus;
  max_points: string;
  claimed_points: string;
  awarded_points: string;
  computed_metrics: Record<string, unknown>;
  evidence_file_ids: string[];
  reviewer_note?: string | null;
  reviewed_at?: string | null;
  sort_order: number;
  created_at: string;
  updated_at: string;
}

export interface CertDetail extends GreenCertification {
  credits: GreenCredit[];
}

export interface ScoreBreakdownRow {
  category: CreditCategory;
  earned_points: string;
  max_points: string;
}

export interface ScoreResult {
  certification_id: string;
  system: CertSystem;
  achieved_points: string;
  max_points: string;
  achieved_level?: TargetLevel | null;
  breakdown: ScoreBreakdownRow[];
}

export interface GapToNextLevel {
  certification_id: string;
  current_level?: TargetLevel | null;
  next_level?: TargetLevel | null;
  points_needed: string;
  candidate_credits: GreenCredit[];
}

export const CERT_SYSTEM_LABEL: Record<CertSystem, string> = {
  lotus_nr: "LOTUS NR",
  lotus_homes: "LOTUS Homes",
  lotus_bio: "LOTUS BIO",
  lotus_intl: "LOTUS Interiors",
  edge: "EDGE",
};

export const TARGET_LEVEL_LABEL: Record<TargetLevel, string> = {
  certified: "Certified",
  silver: "Silver",
  gold: "Gold",
  platinum: "Platinum",
  edge_certified: "EDGE Certified (20%)",
  edge_advanced: "EDGE Advanced (40%)",
  edge_zero: "EDGE Zero",
};

export const CERT_STATUS_LABEL: Record<CertSystem | CertStatus, string> = {
  // Reuse same map for status (TypeScript can't union the keys cleanly).
  lotus_nr: "",
  lotus_homes: "",
  lotus_bio: "",
  lotus_intl: "",
  edge: "",
  planning: "Lập kế hoạch",
  self_assessment: "Tự đánh giá",
  submitted: "Đã nộp hồ sơ",
  provisional: "Chứng nhận tạm",
  final_cert: "Chứng nhận chính thức",
  rejected: "Bị từ chối",
  expired: "Hết hiệu lực",
};

export const CATEGORY_LABEL: Record<CreditCategory, string> = {
  energy: "Năng lượng",
  water: "Nước",
  materials: "Vật liệu",
  ieq: "Chất lượng nội thất",
  site: "Vị trí dự án",
  operations: "Vận hành",
  innovation: "Sáng kiến",
};

export const CREDIT_STATUS_LABEL: Record<CreditStatus, string> = {
  not_attempted: "Chưa thử",
  targeted: "Đã chọn mục tiêu",
  documented: "Đã có tài liệu",
  verified: "Đã thẩm định",
  rejected: "Bị từ chối",
};
