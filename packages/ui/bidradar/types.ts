export type MatchStatus = "new" | "saved" | "pursuing" | "passed";
export type CompetitionLevel = "low" | "moderate" | "high" | "very_high";
export type TenderSource =
  | "mua-sam-cong.gov.vn"
  | "philgeps.gov.ph"
  | "egp.go.th"
  | "eproc.lkpp.go.id"
  | "gebiz.gov.sg"
  | "other";

export interface TenderSummary {
  id: string;
  source: string;
  external_id: string;
  title: string;
  issuer?: string | null;
  type?: string | null;
  budget_vnd?: number | null;
  currency: string;
  country_code: string;
  province?: string | null;
  disciplines?: string[] | null;
  project_types?: string[] | null;
  submission_deadline?: string | null;
  published_at?: string | null;
  raw_url?: string | null;
}

export interface TenderDetail extends TenderSummary {
  description?: string | null;
  scraped_at?: string | null;
}

export interface AIRecommendation {
  match_score: number;
  estimated_value_vnd?: number | null;
  competition_level: CompetitionLevel;
  win_probability: number;
  recommended_bid: boolean;
  reasoning: string;
  strengths: string[];
  risks: string[];
  required_capabilities: string[];
}

export interface TenderMatch {
  id: string;
  tender_id: string;
  match_score?: number | null;
  estimated_value_vnd?: number | null;
  competition_level?: string | null;
  win_probability?: number | null;
  recommended_bid?: boolean | null;
  ai_recommendation?: AIRecommendation | null;
  status: MatchStatus;
  proposal_id?: string | null;
  reviewed_by?: string | null;
  reviewed_at?: string | null;
  created_at: string;
}

export interface TenderMatchWithTender extends TenderMatch {
  tender: TenderSummary;
}

export interface FirmProfile {
  id: string;
  organization_id: string;
  disciplines: string[];
  project_types: string[];
  provinces: string[];
  min_budget_vnd?: number | null;
  max_budget_vnd?: number | null;
  team_size?: number | null;
  active_capacity_pct?: number | null;
  past_wins: Array<Record<string, unknown>>;
  keywords: string[];
  updated_at: string;
}

export interface FirmProfileInput {
  disciplines: string[];
  project_types: string[];
  provinces: string[];
  min_budget_vnd?: number | null;
  max_budget_vnd?: number | null;
  team_size?: number | null;
  active_capacity_pct?: number | null;
  past_wins: Array<Record<string, unknown>>;
  keywords: string[];
}

export interface ScrapeResult {
  source: string;
  tenders_found: number;
  new_tenders: number;
  matches_created: number;
  started_at: string;
  completed_at: string;
}

export interface ScoreMatchesResult {
  scored: number;
  recommended: number;
}

export interface CreateProposalResponse {
  match_id: string;
  proposal_id: string;
  winwork_url: string;
}

export interface WeeklyDigest {
  id: string;
  week_start: string;
  week_end: string;
  top_match_ids: string[];
  sent_to: string[];
  sent_at?: string | null;
  created_at: string;
}
