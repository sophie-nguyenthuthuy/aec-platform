import type { ISODate, UUID } from "./envelope";

export type DailyLogStatus = "draft" | "submitted" | "approved";

export type ObservationKind =
  | "risk"
  | "issue"
  | "delay"
  | "milestone"
  | "safety"
  | "quality"
  | "productivity";

export type ObservationSeverity = "low" | "medium" | "high" | "critical";

export type ObservationSource = "manual" | "llm_extracted" | "siteeye_hit";

export type ObservationStatus =
  | "open"
  | "in_progress"
  | "resolved"
  | "dismissed";

export type EquipmentState = "active" | "idle" | "broken" | "left_site";

export interface ManpowerEntry {
  id?: UUID | null;
  trade: string;
  headcount: number;
  hours_worked?: number | null;
  foreman?: string | null;
  notes?: string | null;
}

export interface EquipmentEntry {
  id?: UUID | null;
  name: string;
  quantity: number;
  hours_used?: number | null;
  state: EquipmentState | string;
  notes?: string | null;
}

export interface Observation {
  id: UUID;
  organization_id: UUID;
  log_id: UUID;
  kind: ObservationKind | string;
  severity: ObservationSeverity | string;
  description: string;
  source: ObservationSource | string;
  related_safety_incident_id?: UUID | null;
  status: ObservationStatus | string;
  resolved_at?: ISODate | null;
  notes?: string | null;
  created_at: ISODate;
}

export interface DailyLogSummary {
  id: UUID;
  organization_id: UUID;
  project_id: UUID;
  log_date: ISODate;
  status: DailyLogStatus | string;
  submitted_at?: ISODate | null;
  approved_at?: ISODate | null;
  created_at: ISODate;
  total_headcount: number;
  open_observations: number;
  high_severity_observations: number;
}

export interface DailyLogDetail {
  summary: DailyLogSummary;
  weather: Record<string, unknown>;
  narrative?: string | null;
  work_completed?: string | null;
  issues_observed?: string | null;
  manpower: ManpowerEntry[];
  equipment: EquipmentEntry[];
  observations: Observation[];
}

export interface PatternsResponse {
  project_id: UUID;
  date_from: ISODate;
  date_to: ISODate;
  days_observed: number;
  avg_headcount: number;
  issue_count_by_kind: Record<string, number>;
  severity_counts: Record<string, number>;
  weather_anomaly_days: Array<{
    log_date: ISODate;
    precipitation_mm: number;
    conditions?: string | null;
  }>;
  most_common_observations: Array<{ description: string; count: number }>;
}
