export type Discipline = "architectural" | "structural" | "mep" | "civil";
export type DocType = "drawing" | "spec" | "report" | "contract" | "rfi" | "submittal";
export type ProcessingStatus = "pending" | "processing" | "ready" | "failed";

export type ConflictStatus = "open" | "resolved" | "dismissed";
export type ConflictSeverity = "critical" | "major" | "minor";
export type ConflictType = "dimension" | "material" | "structural" | "elevation";

export type RfiStatus = "open" | "answered" | "closed";
export type RfiPriority = "low" | "normal" | "high" | "urgent";

export interface BBox {
  x: number;
  y: number;
  width: number;
  height: number;
  page?: number;
}

export interface DocumentSet {
  id: string;
  organization_id: string;
  project_id: string | null;
  name: string;
  discipline: Discipline | null;
  revision: string | null;
  issued_date: string | null;
  created_at: string;
}

export interface Document {
  id: string;
  organization_id: string;
  project_id: string | null;
  document_set_id: string | null;
  file_id: string | null;
  doc_type: DocType | null;
  drawing_number: string | null;
  title: string | null;
  revision: string | null;
  discipline: Discipline | null;
  scale: string | null;
  processing_status: ProcessingStatus;
  extracted_data: Record<string, unknown>;
  thumbnail_url: string | null;
  created_at: string;
}

export interface SourceDocument {
  document_id: string;
  drawing_number: string | null;
  title: string | null;
  discipline: Discipline | null;
  page: number | null;
  excerpt: string;
  bbox: BBox | null;
}

export interface QueryResponse {
  answer: string;
  confidence: number;
  source_documents: SourceDocument[];
  related_questions: string[];
}

export interface ConflictExcerpt {
  document_id: string;
  drawing_number: string | null;
  discipline: Discipline | null;
  page: number | null;
  excerpt: string;
  bbox: BBox | null;
}

export interface Conflict {
  id: string;
  organization_id: string;
  project_id: string | null;
  status: ConflictStatus;
  severity: ConflictSeverity | null;
  conflict_type: ConflictType | null;
  description: string | null;
  document_a_id: string | null;
  chunk_a_id: string | null;
  document_b_id: string | null;
  chunk_b_id: string | null;
  ai_explanation: string | null;
  resolution_notes: string | null;
  detected_at: string;
  resolved_at: string | null;
  resolved_by: string | null;
}

export interface ConflictWithExcerpts extends Conflict {
  document_a: ConflictExcerpt | null;
  document_b: ConflictExcerpt | null;
}

export interface ConflictScanResponse {
  project_id: string;
  scanned_documents: number;
  candidates_evaluated: number;
  conflicts_found: number;
  conflicts: Conflict[];
}

export interface ScheduleRow {
  cells: Record<string, string | number | null>;
}

export interface ExtractedSchedule {
  name: string;
  page: number | null;
  columns: string[];
  rows: ScheduleRow[];
}

export interface ExtractedDimension {
  label: string;
  value_mm: number | null;
  raw: string;
  page: number | null;
  bbox: BBox | null;
}

export interface ExtractedMaterial {
  code: string | null;
  description: string;
  quantity: number | null;
  unit: string | null;
  page: number | null;
}

export interface ExtractResponse {
  document_id: string;
  schedules: ExtractedSchedule[];
  dimensions: ExtractedDimension[];
  materials: ExtractedMaterial[];
  title_block: Record<string, unknown> | null;
}

export interface Rfi {
  id: string;
  organization_id: string;
  project_id: string | null;
  number: string | null;
  subject: string;
  description: string | null;
  status: RfiStatus;
  priority: RfiPriority;
  related_document_ids: string[];
  raised_by: string | null;
  assigned_to: string | null;
  due_date: string | null;
  response: string | null;
  created_at: string;
}
