import type { ISODate, UUID } from "./envelope";

export type ProjectStatus =
  | "planning"
  | "design"
  | "bidding"
  | "construction"
  | "handover"
  | "completed"
  | "on_hold"
  | "cancelled";

export type ProjectType =
  | "residential"
  | "commercial"
  | "industrial"
  | "infrastructure"
  | "mixed_use"
  | "other";

export interface ProjectAddress {
  street?: string;
  ward?: string;
  district?: string;
  city?: string;
  province?: string;
  country?: string;
  [k: string]: unknown;
}

// ---- Per-module roll-ups (mirror apps/api/schemas/projects.py) ----

export interface WinworkStatus {
  proposal_id?: UUID | null;
  proposal_status?: string | null;
  total_fee_vnd?: number | null;
}

export interface CostpulseStatus {
  estimate_count: number;
  approved_count: number;
  latest_estimate_id?: UUID | null;
  latest_total_vnd?: number | null;
}

export interface PulseStatus {
  tasks_todo: number;
  tasks_in_progress: number;
  tasks_done: number;
  open_change_orders: number;
  upcoming_milestones: number;
}

export interface DrawbridgeStatus {
  document_count: number;
  open_rfi_count: number;
  unresolved_conflict_count: number;
}

export interface HandoverStatus {
  package_count: number;
  open_defect_count: number;
  warranty_active_count: number;
  warranty_expiring_count: number;
}

export interface SiteeyeStatus {
  visit_count: number;
  open_safety_incident_count: number;
}

export interface CodeguardStatus {
  compliance_check_count: number;
  permit_checklist_count: number;
}

export interface SchedulepilotStatus {
  schedule_count: number;
  activity_count: number;
  behind_schedule_count: number;
  on_critical_path_count: number;
  overall_slip_days: number;
  percent_complete: number;
}

export interface SubmittalsStatus {
  open_count: number;
  revise_resubmit_count: number;
  approved_count: number;
  designer_court_count: number;
  contractor_court_count: number;
}

export interface DailylogStatus {
  log_count: number;
  open_observation_count: number;
  high_severity_observation_count: number;
  last_log_date?: ISODate | null;
}

export interface ChangeorderStatus {
  total_count: number;
  open_count: number;
  approved_count: number;
  pending_candidates: number;
  total_cost_impact_vnd: number;
  total_schedule_impact_days: number;
}

export interface PunchlistStatus {
  list_count: number;
  open_list_count: number;
  signed_off_list_count: number;
  total_items: number;
  open_items: number;
  verified_items: number;
  high_severity_open_items: number;
}

// ---- Aggregate views ----

export interface ProjectSummary {
  id: UUID;
  organization_id: UUID;
  name: string;
  type?: ProjectType | string | null;
  status: ProjectStatus | string;
  budget_vnd?: number | null;
  area_sqm?: number | null;
  address: ProjectAddress;
  start_date?: ISODate | null;
  end_date?: ISODate | null;
  created_at: ISODate;
  open_tasks: number;
  open_change_orders: number;
  document_count: number;
}

export interface ProjectDetail {
  id: UUID;
  organization_id: UUID;
  name: string;
  type?: ProjectType | string | null;
  status: ProjectStatus | string;
  budget_vnd?: number | null;
  area_sqm?: number | null;
  floors?: number | null;
  address: ProjectAddress;
  start_date?: ISODate | null;
  end_date?: ISODate | null;
  metadata: Record<string, unknown>;
  created_at: ISODate;

  winwork: WinworkStatus;
  costpulse: CostpulseStatus;
  pulse: PulseStatus;
  drawbridge: DrawbridgeStatus;
  handover: HandoverStatus;
  siteeye: SiteeyeStatus;
  codeguard: CodeguardStatus;
  schedulepilot: SchedulepilotStatus;
  submittals: SubmittalsStatus;
  dailylog: DailylogStatus;
  changeorder: ChangeorderStatus;
  punchlist: PunchlistStatus;
}
