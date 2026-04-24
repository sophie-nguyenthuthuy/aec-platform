export type PackageStatus = "draft" | "in_review" | "approved" | "delivered";

export type CloseoutCategory =
  | "drawings"
  | "documents"
  | "certificates"
  | "warranties"
  | "manuals"
  | "permits"
  | "testing"
  | "other";

export type CloseoutStatus =
  | "pending"
  | "in_progress"
  | "done"
  | "not_applicable";

export type Discipline =
  | "architecture"
  | "structure"
  | "mep"
  | "electrical"
  | "plumbing"
  | "hvac"
  | "fire"
  | "landscape"
  | "interior";

export type OmManualStatus = "draft" | "generating" | "ready" | "failed";

export type WarrantyStatus = "active" | "expiring" | "expired" | "claimed";

export type DefectStatus =
  | "open"
  | "assigned"
  | "in_progress"
  | "resolved"
  | "rejected";

export type DefectPriority = "low" | "medium" | "high" | "critical";

export interface HandoverPackage {
  id: string;
  organization_id: string;
  project_id: string;
  name: string;
  status: PackageStatus;
  scope_summary: Record<string, unknown>;
  export_file_id?: string | null;
  delivered_at?: string | null;
  created_by?: string | null;
  created_at: string;
}

export interface PackageSummary {
  id: string;
  project_id: string;
  name: string;
  status: PackageStatus;
  closeout_total: number;
  closeout_done: number;
  warranty_expiring: number;
  open_defects: number;
  delivered_at?: string | null;
  created_at: string;
}

export interface CloseoutItem {
  id: string;
  package_id: string;
  category: CloseoutCategory;
  title: string;
  description?: string | null;
  required: boolean;
  status: CloseoutStatus;
  assignee_id?: string | null;
  file_ids: string[];
  notes?: string | null;
  sort_order: number;
  updated_at: string;
}

export interface PackageDetail extends HandoverPackage {
  closeout_items: CloseoutItem[];
}

export interface AsBuiltChangelogEntry {
  version: number;
  file_id: string;
  change_note?: string | null;
  recorded_at: string;
}

export interface AsBuiltDrawing {
  id: string;
  project_id: string;
  package_id?: string | null;
  drawing_code: string;
  discipline: Discipline;
  title: string;
  current_version: number;
  current_file_id?: string | null;
  superseded_file_ids: string[];
  changelog: AsBuiltChangelogEntry[];
  last_updated_at: string;
}

export interface EquipmentSpec {
  tag: string;
  name: string;
  discipline: Discipline;
  manufacturer?: string | null;
  model?: string | null;
  serial?: string | null;
  location?: string | null;
  capacity?: string | null;
  notes?: string | null;
}

export interface MaintenanceTask {
  equipment_tag: string;
  task: string;
  frequency: string;
  duration_minutes?: number | null;
  tools: string[];
  safety?: string | null;
}

export interface OmManual {
  id: string;
  project_id: string;
  package_id?: string | null;
  title: string;
  discipline: Discipline;
  status: OmManualStatus;
  equipment: EquipmentSpec[];
  maintenance_schedule: MaintenanceTask[];
  source_file_ids: string[];
  pdf_file_id?: string | null;
  ai_job_id?: string | null;
  generated_at: string;
  created_by?: string | null;
}

export interface WarrantyItem {
  id: string;
  project_id: string;
  package_id?: string | null;
  item_name: string;
  category?: string | null;
  vendor?: string | null;
  contract_file_id?: string | null;
  warranty_period_months?: number | null;
  start_date?: string | null;
  expiry_date?: string | null;
  coverage?: string | null;
  claim_contact: Record<string, unknown>;
  status: WarrantyStatus;
  notes?: string | null;
  days_to_expiry?: number | null;
  created_at: string;
}

export interface Defect {
  id: string;
  project_id: string;
  package_id?: string | null;
  title: string;
  description?: string | null;
  location?: Record<string, unknown> | null;
  photo_file_ids: string[];
  status: DefectStatus;
  priority: DefectPriority;
  assignee_id?: string | null;
  reported_by?: string | null;
  reported_at: string;
  resolved_at?: string | null;
  resolution_notes?: string | null;
}
