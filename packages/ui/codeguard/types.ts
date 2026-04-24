export type Severity = "critical" | "major" | "minor";
export type FindingStatus = "FAIL" | "WARN" | "PASS";
export type RegulationCategory =
  | "fire_safety"
  | "accessibility"
  | "structure"
  | "zoning"
  | "energy";

export type ChecklistItemStatus = "pending" | "in_progress" | "done" | "not_applicable";

export interface Citation {
  regulation_id: string;
  regulation: string;
  section: string;
  excerpt: string;
  source_url?: string | null;
}

export interface Finding {
  status: FindingStatus;
  severity: Severity;
  category: RegulationCategory;
  title: string;
  description: string;
  resolution?: string | null;
  citation?: Citation | null;
}

export interface ChecklistItem {
  id: string;
  title: string;
  description?: string | null;
  regulation_ref?: string | null;
  required: boolean;
  status: ChecklistItemStatus;
  assignee_id?: string | null;
  notes?: string | null;
  updated_at?: string | null;
}

export interface RegulationSummary {
  id: string;
  country_code: string;
  jurisdiction?: string | null;
  code_name: string;
  category?: RegulationCategory | null;
  effective_date?: string | null;
  expiry_date?: string | null;
  source_url?: string | null;
  language: string;
}

export interface QueryResponse {
  answer: string;
  confidence: number;
  citations: Citation[];
  related_questions: string[];
  check_id?: string | null;
}

export interface ScanResponse {
  check_id: string;
  status: string;
  total: number;
  pass_count: number;
  warn_count: number;
  fail_count: number;
  findings: Finding[];
}

export interface PermitChecklist {
  id: string;
  project_id?: string | null;
  jurisdiction: string;
  project_type: string;
  items: ChecklistItem[];
  generated_at: string;
  completed_at?: string | null;
}
