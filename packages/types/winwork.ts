import type { UUID, ISODate } from "./envelope";

export type ProposalStatus = "draft" | "sent" | "won" | "lost" | "expired";
export type Discipline = "architecture" | "structural" | "mep" | "civil";

export interface ScopeItem {
  id: string;
  phase: string;
  title: string;
  description?: string;
  deliverables: string[];
  hours_estimate?: number;
  fee_vnd?: number;
}

export interface ScopeOfWork {
  items: ScopeItem[];
}

export interface FeeLine {
  phase: string;
  label: string;
  amount_vnd: number;
  percent?: number;
  notes?: string;
}

export interface FeeBreakdown {
  lines: FeeLine[];
  subtotal_vnd: number;
  vat_vnd: number;
  total_vnd: number;
}

export interface Proposal {
  id: UUID;
  project_id: UUID | null;
  title: string;
  status: ProposalStatus;
  client_name: string | null;
  client_email: string | null;
  scope_of_work: ScopeOfWork | null;
  fee_breakdown: FeeBreakdown | null;
  total_fee_vnd: number | null;
  total_fee_currency: string;
  valid_until: ISODate | null;
  ai_generated: boolean;
  ai_confidence: number | null;
  notes: string | null;
  sent_at: string | null;
  responded_at: string | null;
  created_by: UUID | null;
  created_at: string;
}

export interface ProposalTemplate {
  id: UUID;
  name: string;
  discipline: Discipline | null;
  project_types: string[];
  content: Record<string, unknown>;
  is_default: boolean;
}

export interface FeeBenchmark {
  id: UUID;
  discipline: Discipline;
  project_type: string;
  country_code: string;
  province: string | null;
  area_sqm_min: number | null;
  area_sqm_max: number | null;
  fee_percent_low: number;
  fee_percent_mid: number;
  fee_percent_high: number;
  source: string | null;
  valid_from: ISODate | null;
  valid_to: ISODate | null;
}

export interface ProposalGenerateRequest {
  project_type: string;
  area_sqm: number;
  floors: number;
  location: string;
  scope_items: string[];
  client_brief: string;
  discipline: Discipline;
  language?: "vi" | "en";
  project_id?: UUID | null;
}

export interface ProposalGenerateResponse {
  proposal: Proposal;
  ai_job_id: UUID;
}

export interface FeeEstimateRequest {
  discipline: Discipline;
  project_type: string;
  area_sqm: number;
  country_code?: string;
  province?: string;
}

export interface FeeEstimateResponse {
  fee_low_vnd: number;
  fee_mid_vnd: number;
  fee_high_vnd: number;
  fee_percent_low: number;
  fee_percent_mid: number;
  fee_percent_high: number;
  basis: string;
  confidence: number;
}

export interface WinRateAnalytics {
  total: number;
  won: number;
  lost: number;
  pending: number;
  win_rate: number;
  avg_fee_vnd: number;
  by_project_type: Array<{ project_type: string; total: number; won: number; win_rate: number }>;
  by_month: Array<{ month: string; total: number; won: number; lost: number }>;
}

export interface ProposalOutcomeUpdate {
  status: "won" | "lost";
  reason?: string;
  actual_fee_vnd?: number;
}

export interface SendProposalRequest {
  subject?: string;
  message?: string;
  cc?: string[];
}
