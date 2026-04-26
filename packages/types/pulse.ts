import type { UUID, ISODate } from "./envelope";

export type TaskStatus = "todo" | "in_progress" | "review" | "done" | "blocked";
export type Priority = "low" | "normal" | "high" | "urgent";
export type Phase = "design" | "permit" | "construction" | "closeout";
export type MilestoneStatus = "upcoming" | "achieved" | "missed";
export type ChangeOrderStatus = "draft" | "submitted" | "approved" | "rejected";
export type ChangeOrderInitiator =
  | "client"
  | "contractor"
  | "designer"
  /** Auto-emitted by COSTPULSE when an approved estimate's total deviates
   *  >2% from the project's prior approved baseline. The accompanying
   *  `ai_analysis` carries `{ source: "costpulse.estimate_approved",
   *  prior_estimate_id, new_estimate_id, variance_pct, ... }`. */
  | "costpulse";
export type ReportStatus = "draft" | "sent" | "archived";
export type RAG = "green" | "amber" | "red";

export interface Task {
  id: UUID;
  organization_id: UUID;
  project_id: UUID;
  parent_id: UUID | null;
  title: string;
  description: string | null;
  status: TaskStatus;
  priority: Priority;
  assignee_id: UUID | null;
  phase: Phase | null;
  discipline: string | null;
  start_date: ISODate | null;
  due_date: ISODate | null;
  completed_at: string | null;
  position: number | null;
  tags: string[];
  created_by: UUID | null;
  created_at: string;
}

export interface TaskCreate {
  project_id: UUID;
  title: string;
  description?: string | null;
  status?: TaskStatus;
  priority?: Priority;
  assignee_id?: UUID | null;
  phase?: Phase | null;
  discipline?: string | null;
  start_date?: ISODate | null;
  due_date?: ISODate | null;
  position?: number | null;
  tags?: string[];
  parent_id?: UUID | null;
}

export type TaskUpdate = Partial<Omit<TaskCreate, "project_id">>;

export interface TaskBulkItem {
  id: UUID;
  status?: TaskStatus;
  phase?: Phase;
  position?: number;
  assignee_id?: UUID | null;
}

export interface TaskBulkUpdate {
  items: TaskBulkItem[];
}

export interface Milestone {
  id: UUID;
  organization_id: UUID;
  project_id: UUID;
  name: string;
  due_date: ISODate;
  status: MilestoneStatus;
  achieved_at: string | null;
}

export interface ChangeOrderAIAnalysis {
  root_cause: "design_change" | "scope_creep" | "site_condition" | "error" | "other";
  cost_breakdown: Record<string, unknown>;
  schedule_analysis: Record<string, unknown>;
  contract_clauses: string[];
  recommendation: "approve" | "negotiate" | "reject" | "request_more_info";
  reasoning: string;
  confidence: number;
}

/** Provenance payload for change orders auto-emitted by COSTPULSE when an
 *  approved estimate's total deviates from the project's prior approved
 *  baseline. Discriminated from the AI-analysis shape via `source`. */
export interface CostpulseVarianceAnalysis {
  source: "costpulse.estimate_approved";
  prior_estimate_id: UUID;
  new_estimate_id: UUID;
  prior_total_vnd: number;
  new_total_vnd: number;
  delta_vnd: number;
  variance_pct: number;
}

export type ChangeOrderAnalysis =
  | ChangeOrderAIAnalysis
  | CostpulseVarianceAnalysis;

export function isCostpulseVariance(
  a: ChangeOrderAnalysis | null | undefined,
): a is CostpulseVarianceAnalysis {
  return !!a && (a as CostpulseVarianceAnalysis).source === "costpulse.estimate_approved";
}

export interface ChangeOrder {
  id: UUID;
  organization_id: UUID;
  project_id: UUID;
  number: string;
  title: string;
  description: string | null;
  status: ChangeOrderStatus;
  initiator: ChangeOrderInitiator | null;
  cost_impact_vnd: number | null;
  schedule_impact_days: number | null;
  ai_analysis: ChangeOrderAnalysis | null;
  submitted_at: string | null;
  approved_at: string | null;
  approved_by: UUID | null;
  created_at: string;
}

export interface ChangeOrderCreate {
  project_id: UUID;
  number: string;
  title: string;
  description?: string | null;
  initiator?: ChangeOrderInitiator | null;
  cost_impact_vnd?: number | null;
  schedule_impact_days?: number | null;
}

export interface ChangeOrderApproval {
  decision: "approve" | "reject";
  notes?: string;
}

export interface ActionItem {
  title: string;
  owner: string | null;
  owner_user_id: UUID | null;
  deadline: ISODate | null;
}

export interface MeetingStructured {
  summary: string;
  decisions: string[];
  action_items: ActionItem[];
  risks: string[];
  next_meeting: ISODate | null;
}

export interface MeetingNoteCreate {
  project_id: UUID;
  meeting_date: ISODate;
  attendees: string[];
  raw_notes: string;
}

export interface MeetingNote {
  id: UUID;
  organization_id: UUID;
  project_id: UUID;
  meeting_date: ISODate;
  attendees: string[];
  raw_notes: string | null;
  ai_structured: MeetingStructured | null;
  created_by: UUID | null;
  created_at: string;
}

export interface MeetingStructureRequest {
  raw_notes: string;
  language?: "vi" | "en";
  project_id?: UUID;
  meeting_note_id?: UUID;
  persist?: boolean;
}

export interface ClientReportContent {
  header_summary: string;
  progress_section: {
    narrative?: string;
    highlights?: string[];
    progress_pct?: number;
  };
  photos_section: Array<{ url: string; caption?: string }>;
  financials: {
    narrative?: string;
    summary?: {
      spent?: number | null;
      budget?: number | null;
      variance?: number | null;
    };
  } | null;
  issues: Array<{ title: string; status: string; impact: string }>;
  next_steps: string[];
}

export interface ClientReport {
  id: UUID;
  organization_id: UUID;
  project_id: UUID;
  report_date: ISODate;
  period: string | null;
  content: ClientReportContent | null;
  rendered_html: string | null;
  pdf_url: string | null;
  status: ReportStatus;
  sent_at: string | null;
  sent_to: string[] | null;
}

export interface ReportGenerateRequest {
  project_id: UUID;
  period: string;
  date_from?: ISODate;
  date_to?: ISODate;
  language?: "vi" | "en";
  include_photos?: boolean;
  include_financials?: boolean;
}

export interface ReportSendRequest {
  recipients: string[];
  subject?: string;
  message?: string;
}

export interface TaskCountsByStatus {
  todo: number;
  in_progress: number;
  review: number;
  done: number;
  blocked: number;
}

export interface ProjectDashboard {
  project_id: UUID;
  rag_status: RAG;
  progress_pct: number;
  task_counts: TaskCountsByStatus;
  overdue_tasks: number;
  upcoming_milestones: Milestone[];
  open_change_orders: number;
  open_cost_impact_vnd: number;
  last_report_date: ISODate | null;
  alerts: string[];
}
