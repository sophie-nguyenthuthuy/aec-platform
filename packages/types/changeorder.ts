import type { ISODate, UUID } from "./envelope";

export type CoStatus =
  | "draft"
  | "submitted"
  | "reviewed"
  | "approved"
  | "rejected"
  | "executed"
  | "cancelled";

export type CoSourceKind =
  | "rfi"
  | "observation"
  | "email"
  | "manual"
  | "external";

export type LineKind = "add" | "delete" | "substitute";

export type CandidateSourceKind = "rfi" | "email" | "manual_paste";

export interface ChangeOrder {
  id: UUID;
  organization_id: UUID;
  project_id: UUID;
  number: string;
  title: string;
  description?: string | null;
  status: CoStatus | string;
  initiator?: string | null;
  cost_impact_vnd?: number | null;
  schedule_impact_days?: number | null;
  ai_analysis?: Record<string, unknown> | null;
  submitted_at?: ISODate | null;
  approved_at?: ISODate | null;
  approved_by?: UUID | null;
  created_at: ISODate;
}

export interface Source {
  id: UUID;
  organization_id: UUID;
  change_order_id: UUID;
  source_kind: CoSourceKind | string;
  rfi_id?: UUID | null;
  observation_id?: UUID | null;
  payload: Record<string, unknown>;
  notes?: string | null;
  created_at: ISODate;
}

export interface LineItem {
  id: UUID;
  organization_id: UUID;
  change_order_id: UUID;
  description: string;
  line_kind: LineKind | string;
  spec_section?: string | null;
  quantity?: number | null;
  unit?: string | null;
  unit_cost_vnd?: number | null;
  cost_vnd?: number | null;
  schedule_impact_days?: number | null;
  schedule_activity_id?: UUID | null;
  sort_order: number;
  notes?: string | null;
  created_at: ISODate;
}

export interface Approval {
  id: UUID;
  organization_id: UUID;
  change_order_id: UUID;
  from_status?: CoStatus | string | null;
  to_status: CoStatus | string;
  actor_id?: UUID | null;
  notes?: string | null;
  created_at: ISODate;
}

export interface ChangeOrderDetail {
  change_order: ChangeOrder;
  sources: Source[];
  line_items: LineItem[];
  approvals: Approval[];
}

export interface CandidateProposal {
  title: string;
  description: string;
  line_items?: Partial<LineItem>[];
  cost_impact_vnd_estimate?: number | null;
  schedule_impact_days_estimate?: number | null;
  confidence_pct?: number | null;
  rationale?: string | null;
}

export interface Candidate {
  id: UUID;
  organization_id: UUID;
  project_id: UUID;
  source_kind: CandidateSourceKind | string;
  source_rfi_id?: UUID | null;
  source_text_snippet?: string | null;
  proposal: CandidateProposal & Record<string, unknown>;
  model_version: string;
  accepted_co_id?: UUID | null;
  accepted_at?: ISODate | null;
  rejected_at?: ISODate | null;
  rejected_reason?: string | null;
  actor_id?: UUID | null;
  created_at: ISODate;
}
