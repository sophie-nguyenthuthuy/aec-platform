// Shared TypeScript types for the SiteEye module.
// Mirrors apps/api/schemas/siteeye.py.

export type UUID = string;
export type ISODate = string;
export type ISODateTime = string;

export type SafetyStatus = "clear" | "warning" | "critical";

export type IncidentType =
  | "no_ppe"
  | "unsafe_scaffold"
  | "open_trench"
  | "fire_hazard"
  | "electrical_hazard";

export type IncidentSeverity = "low" | "medium" | "high" | "critical";
export type IncidentStatus = "open" | "acknowledged" | "resolved" | "dismissed";

export type ConstructionPhase =
  | "site_prep"
  | "foundation"
  | "structure"
  | "envelope"
  | "mep"
  | "finishes"
  | "exterior"
  | "handover";

export type ScheduleStatus = "on_track" | "ahead" | "behind" | "unknown";

export interface GeoLocation {
  lat: number;
  lng: number;
  accuracy_m?: number | null;
}

export interface SiteVisit {
  id: UUID;
  project_id: UUID;
  visit_date: ISODate;
  location: GeoLocation | null;
  reported_by: UUID | null;
  weather: string | null;
  workers_count: number | null;
  notes: string | null;
  ai_summary: string | null;
  photo_count: number;
  created_at: ISODateTime;
}

export interface SiteVisitCreate {
  project_id: UUID;
  visit_date: ISODate;
  location?: GeoLocation | null;
  weather?: string | null;
  workers_count?: number | null;
  notes?: string | null;
}

export interface PhotoDetection {
  label: string;
  confidence: number;
  bbox: [number, number, number, number];
}

export interface PhotoAIAnalysis {
  description: string | null;
  detected_elements: string[];
  safety_flags: PhotoDetection[];
  progress_indicators: Record<string, unknown>;
  phase: ConstructionPhase | null;
  completion_hint: number | null;
}

export interface SitePhoto {
  id: UUID;
  project_id: UUID;
  site_visit_id: UUID | null;
  file_id: UUID | null;
  thumbnail_url: string | null;
  taken_at: ISODateTime | null;
  location: GeoLocation | null;
  tags: string[];
  ai_analysis: PhotoAIAnalysis | null;
  safety_status: SafetyStatus | null;
  created_at: ISODateTime;
}

export interface PhotoUploadItem {
  file_id: UUID;
  taken_at?: ISODateTime | null;
  location?: GeoLocation | null;
  thumbnail_url?: string | null;
}

export interface PhotoBatchUploadRequest {
  project_id: UUID;
  site_visit_id?: UUID | null;
  photos: PhotoUploadItem[];
}

export interface PhotoBatchUploadResponse {
  accepted: number;
  photo_ids: UUID[];
  job_id: UUID;
}

export interface ProgressSnapshot {
  id: UUID;
  project_id: UUID;
  snapshot_date: ISODate;
  overall_progress_pct: number;
  phase_progress: Record<string, number>;
  ai_notes: string | null;
  photo_ids: UUID[];
  created_at: ISODateTime;
}

export interface ProgressTimeline {
  project_id: UUID;
  snapshots: ProgressSnapshot[];
  baseline_schedule: Record<string, unknown> | null;
  schedule_status: ScheduleStatus;
}

export interface SafetyIncident {
  id: UUID;
  project_id: UUID;
  detected_at: ISODateTime;
  incident_type: IncidentType;
  severity: IncidentSeverity;
  photo_id: UUID | null;
  detection_box: Record<string, unknown> | null;
  ai_description: string | null;
  status: IncidentStatus;
  acknowledged_by: UUID | null;
  resolved_at: ISODateTime | null;
}

export interface ReportKPIs {
  days_elapsed: number;
  days_remaining: number | null;
  schedule_status: ScheduleStatus;
  overall_progress_pct: number;
}

export interface ReportContent {
  executive_summary: string;
  progress_this_week: { overall?: string; by_phase?: Record<string, number> };
  safety_summary: { incidents?: number; status?: string; notes?: string };
  issues_and_risks: string[];
  next_week_plan: string[];
  photos_highlighted: UUID[];
  kpis: ReportKPIs;
}

export interface WeeklyReport {
  id: UUID;
  project_id: UUID;
  week_start: ISODate;
  week_end: ISODate;
  content: ReportContent | null;
  rendered_html: string | null;
  pdf_url: string | null;
  sent_to: string[];
  sent_at: ISODateTime | null;
  created_at: ISODateTime;
}

// ---------- Envelope ----------

export interface EnvelopeMeta {
  page?: number | null;
  per_page?: number | null;
  total?: number | null;
}

export interface EnvelopeError {
  code: string;
  message: string;
  field?: string | null;
}

export interface Envelope<T> {
  data: T | null;
  meta: EnvelopeMeta | null;
  errors: EnvelopeError[] | null;
}
