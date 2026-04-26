import type { ISODate, UUID } from "./envelope";

export type ActivityModule =
  | "pulse"
  | "siteeye"
  | "handover"
  | "winwork"
  | "drawbridge"
  | "costpulse"
  | "codeguard";

export type ActivityEventType =
  | "change_order_created"
  | "task_completed"
  | "safety_incident_detected"
  | "defect_reported"
  | "proposal_outcome_marked"
  | "rfi_raised"
  | "handover_package_delivered";

export interface ActivityEvent {
  id: UUID;
  project_id: UUID | null;
  project_name: string | null;
  module: ActivityModule;
  event_type: ActivityEventType;
  title: string;
  description: string | null;
  timestamp: ISODate;
  actor_id: UUID | null;
  metadata: Record<string, unknown>;
}

export interface ActivityFilters {
  project_id?: UUID;
  module?: ActivityModule;
  /** Rolling window in days (1-365). Default 30. */
  since_days?: number;
  limit?: number;
  offset?: number;
}
