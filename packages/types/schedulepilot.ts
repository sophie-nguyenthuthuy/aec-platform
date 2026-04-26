import type { ISODate, UUID } from "./envelope";

export type ScheduleStatus = "draft" | "baselined" | "active" | "archived";

export type ActivityType = "task" | "milestone" | "summary";

export type ActivityStatus =
  | "not_started"
  | "in_progress"
  | "complete"
  | "on_hold";

export type DependencyType = "fs" | "ss" | "ff" | "sf";

export interface ScheduleSummary {
  id: UUID;
  organization_id: UUID;
  project_id: UUID;
  name: string;
  status: ScheduleStatus | string;
  baseline_set_at?: ISODate | null;
  data_date?: ISODate | null;
  created_at: ISODate;
  updated_at: ISODate;
  activity_count: number;
  on_critical_path_count: number;
  behind_schedule_count: number;
  percent_complete: number;
}

export interface Activity {
  id: UUID;
  organization_id: UUID;
  schedule_id: UUID;
  code: string;
  name: string;
  activity_type: ActivityType | string;
  planned_start?: ISODate | null;
  planned_finish?: ISODate | null;
  planned_duration_days?: number | null;
  baseline_start?: ISODate | null;
  baseline_finish?: ISODate | null;
  actual_start?: ISODate | null;
  actual_finish?: ISODate | null;
  percent_complete: number;
  status: ActivityStatus | string;
  assignee_id?: UUID | null;
  notes?: string | null;
  sort_order: number;
  created_at: ISODate;
  updated_at: ISODate;
}

export interface Dependency {
  id: UUID;
  organization_id: UUID;
  predecessor_id: UUID;
  successor_id: UUID;
  relationship_type: DependencyType | string;
  lag_days: number;
  created_at: ISODate;
}

export interface TopRisk {
  activity_id: UUID;
  code: string;
  name: string;
  expected_slip_days: number;
  reason: string;
  mitigation: string;
}

export interface RiskAssessment {
  id: UUID;
  organization_id: UUID;
  schedule_id: UUID;
  generated_at: ISODate;
  model_version?: string | null;
  data_date_used?: ISODate | null;
  overall_slip_days: number;
  confidence_pct?: number | null;
  critical_path_codes: string[];
  top_risks: TopRisk[];
  input_summary: Record<string, unknown>;
  notes?: string | null;
}

export interface ScheduleDetail {
  schedule: ScheduleSummary;
  activities: Activity[];
  dependencies: Dependency[];
  latest_risk_assessment: RiskAssessment | null;
}
