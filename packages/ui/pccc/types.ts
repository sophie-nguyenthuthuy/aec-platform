export type CertType = "design" | "acceptance" | "recert";

export type HazardCategory = "A" | "B" | "C" | "D" | "E" | "F";

export type BuildingClass = "CO1" | "CO2" | "CO3" | "CO4";

export type CertStatus =
  | "planning"
  | "submitted"
  | "inspection_scheduled"
  | "rfi"
  | "approved"
  | "conditional"
  | "rejected"
  | "expired";

export type InspectionResult =
  | "pass"
  | "conditional_pass"
  | "fail"
  | "rescheduled";

export type ChecklistItemStatus =
  | "pending"
  | "compliant"
  | "non_compliant"
  | "not_applicable";

export type FindingSeverity =
  | "info"
  | "minor"
  | "medium"
  | "major"
  | "critical";

export interface FireCert {
  id: string;
  organization_id: string;
  project_id: string;
  cert_type: CertType;
  reference_no: string;
  hazard_category: HazardCategory;
  building_class: BuildingClass;
  height_m?: string | null;
  floors_above?: number | null;
  floors_below?: number | null;
  area_sqm?: string | null;
  occupant_load?: number | null;
  pc07_unit: string;
  status: CertStatus;
  submitted_date?: string | null;
  inspection_date?: string | null;
  decision_date?: string | null;
  decision_number?: string | null;
  expiry_date?: string | null;
  notes?: string | null;
  legal_basis: string[];
  created_at: string;
  updated_at: string;
}

export interface CertSummary {
  id: string;
  project_id: string;
  cert_type: CertType;
  reference_no: string;
  hazard_category: HazardCategory;
  building_class: BuildingClass;
  status: CertStatus;
  pc07_unit: string;
  decision_date?: string | null;
  expiry_date?: string | null;
  checklist_total: number;
  checklist_compliant: number;
  checklist_non_compliant: number;
  inspection_count: number;
  created_at: string;
}

export interface FireInspection {
  id: string;
  organization_id: string;
  cert_id: string;
  round_number: number;
  inspection_date: string;
  inspector_name: string;
  inspector_org?: string | null;
  overall_result: InspectionResult;
  findings: Record<string, unknown>[];
  summary?: string | null;
  next_steps?: string | null;
  report_file_id?: string | null;
  created_at: string;
}

export interface ChecklistItem {
  id: string;
  organization_id: string;
  cert_id: string;
  clause_ref: string;
  category: string;
  description: string;
  status: ChecklistItemStatus;
  reviewer_note?: string | null;
  reviewer_user_id?: string | null;
  evidence_file_ids: string[];
  drawing_refs: string[];
  severity: FindingSeverity;
  sort_order: number;
  reviewed_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface CertDetail extends FireCert {
  inspections: FireInspection[];
  checklist: ChecklistItem[];
}

export interface CertAlert {
  cert_id: string;
  project_id: string;
  code: "expiring_soon" | "non_compliances_open" | "inspection_overdue";
  severity: "info" | "warning" | "critical";
  message: string;
  days_until?: number | null;
  expiry_date?: string | null;
}

export const CERT_TYPE_LABEL: Record<CertType, string> = {
  design: "Thẩm duyệt thiết kế",
  acceptance: "Nghiệm thu PCCC",
  recert: "Tái thẩm định",
};

export const CERT_STATUS_LABEL: Record<CertStatus, string> = {
  planning: "Lập kế hoạch",
  submitted: "Đã nộp",
  inspection_scheduled: "Đã hẹn kiểm tra",
  rfi: "Yêu cầu bổ sung",
  approved: "Đã phê duyệt",
  conditional: "Phê duyệt có điều kiện",
  rejected: "Bị từ chối",
  expired: "Hết hiệu lực",
};

export const HAZARD_CATEGORY_LABEL: Record<HazardCategory, string> = {
  A: "A (nguy hiểm cháy nổ rất cao)",
  B: "B (nguy hiểm cháy nổ cao)",
  C: "C (nguy hiểm cháy)",
  D: "D (ít nguy hiểm)",
  E: "E (nguy hiểm thấp)",
  F: "F (an toàn cháy)",
};

export const BUILDING_CLASS_LABEL: Record<BuildingClass, string> = {
  CO1: "CO1 — không cháy",
  CO2: "CO2 — khó cháy",
  CO3: "CO3 — cháy chậm",
  CO4: "CO4 — cháy",
};

export const INSPECTION_RESULT_LABEL: Record<InspectionResult, string> = {
  pass: "Đạt",
  conditional_pass: "Đạt có điều kiện",
  fail: "Không đạt",
  rescheduled: "Hẹn lại",
};
