export type EmploymentType =
  | "direct"
  | "subcontractor"
  | "temporary"
  | "foreign";

export type WorkerStatus = "active" | "inactive" | "terminated";

export type SafetyGroup = "1" | "2" | "3" | "4" | "5" | "6";

export type TrainingStatus = "valid" | "expired" | "revoked";

export type InsuranceStatus =
  | "enrolled"
  | "pending"
  | "not_required"
  | "terminated"
  | "superseded";

export type PermitExemptionType =
  | "required"
  | "exempt_short_term"
  | "exempt_intracompany"
  | "exempt_other";

export type PermitStatus =
  | "pending"
  | "approved"
  | "rejected"
  | "expired"
  | "cancelled";

export interface Worker {
  id: string;
  organization_id: string;
  full_name: string;
  dob?: string | null;
  gender?: string | null;
  id_no?: string | null;
  phone?: string | null;
  address?: string | null;
  trade: string;
  employment_type: EmploymentType;
  employer_org_name?: string | null;
  nationality: string;
  status: WorkerStatus;
  hire_date?: string | null;
  termination_date?: string | null;
  notes?: string | null;
  created_at: string;
  updated_at: string;
}

export interface WorkerSummary {
  id: string;
  full_name: string;
  trade: string;
  employment_type: EmploymentType;
  nationality: string;
  status: WorkerStatus;
  id_no?: string | null;
  phone?: string | null;
  has_valid_safety_training: boolean;
  has_active_insurance: boolean;
  has_active_permit: boolean;
  active_assignment_count: number;
  created_at: string;
}

export interface SafetyTraining {
  id: string;
  worker_id: string;
  group: SafetyGroup;
  training_org: string;
  training_date: string;
  valid_until: string;
  certificate_no?: string | null;
  status: TrainingStatus;
}

export interface InsuranceEnrollment {
  id: string;
  worker_id: string;
  basic_salary_vnd: number;
  bhxh_enrolled: boolean;
  bhyt_enrolled: boolean;
  bhtn_enrolled: boolean;
  bhxh_no?: string | null;
  enrolled_at?: string | null;
  status: InsuranceStatus;
}

export interface ForeignPermit {
  id: string;
  worker_id: string;
  nationality: string;
  passport_no: string;
  job_position: string;
  permit_no?: string | null;
  issue_date?: string | null;
  expiry_date?: string | null;
  exemption_type: PermitExemptionType;
  status: PermitStatus;
}

export interface WorkforceAlert {
  worker_id: string;
  code: string;
  severity: "info" | "warning" | "critical";
  message: string;
  related_id?: string | null;
  days_until?: number | null;
  expiry_date?: string | null;
}

export interface ContributionBreakdown {
  bhxh_employer: number;
  bhxh_employee: number;
  bhyt_employer: number;
  bhyt_employee: number;
  bhtn_employer: number;
  bhtn_employee: number;
  kpcd_employer: number;
  employer_total: number;
  employee_total: number;
}

export const EMPLOYMENT_TYPE_LABEL: Record<EmploymentType, string> = {
  direct: "Trực tiếp",
  subcontractor: "Nhà thầu phụ",
  temporary: "Thời vụ",
  foreign: "Nước ngoài",
};

export const WORKER_STATUS_LABEL: Record<WorkerStatus, string> = {
  active: "Đang làm việc",
  inactive: "Tạm nghỉ",
  terminated: "Đã nghỉ",
};

export const SAFETY_GROUP_LABEL: Record<SafetyGroup, string> = {
  "1": "Nhóm 1 — Cán bộ quản lý cấp cao",
  "2": "Nhóm 2 — Cán bộ ATVSLĐ",
  "3": "Nhóm 3 — Lao động nghề nguy hiểm",
  "4": "Nhóm 4 — Lao động khác",
  "5": "Nhóm 5 — Y tế & sơ cấp cứu",
  "6": "Nhóm 6 — Giám sát ATVSLĐ",
};

const VND_FMT = new Intl.NumberFormat("vi-VN");
export function formatVnd(amount: number): string {
  return `${VND_FMT.format(amount)} ₫`;
}
