import type { ISODate, UUID } from "./envelope";

export type SubmittalType =
  | "shop_drawing"
  | "sample"
  | "product_data"
  | "mock_up"
  | "certificate"
  | "other";

export type SubmittalStatus =
  | "pending_review"
  | "under_review"
  | "approved"
  | "approved_as_noted"
  | "revise_resubmit"
  | "rejected"
  | "superseded";

export type BallInCourt = "designer" | "contractor" | "unassigned";

export type RevisionStatus =
  | "pending_review"
  | "approved"
  | "approved_as_noted"
  | "revise_resubmit"
  | "rejected";

export interface Submittal {
  id: UUID;
  organization_id: UUID;
  project_id: UUID;
  package_number: string;
  title: string;
  description?: string | null;
  submittal_type: SubmittalType | string;
  spec_section?: string | null;
  csi_division?: string | null;
  status: SubmittalStatus | string;
  current_revision: number;
  ball_in_court: BallInCourt | string;
  contractor_id?: UUID | null;
  submitted_by?: UUID | null;
  due_date?: ISODate | null;
  submitted_at?: ISODate | null;
  closed_at?: ISODate | null;
  notes?: string | null;
  created_at: ISODate;
  updated_at: ISODate;
}

export interface SubmittalRevision {
  id: UUID;
  organization_id: UUID;
  submittal_id: UUID;
  revision_number: number;
  file_id?: UUID | null;
  review_status: RevisionStatus | string;
  reviewer_id?: UUID | null;
  reviewed_at?: ISODate | null;
  reviewer_notes?: string | null;
  annotations: Record<string, unknown>[];
  created_at: ISODate;
}

export interface SubmittalDetail {
  submittal: Submittal;
  revisions: SubmittalRevision[];
}

// ---- RFI AI ----

export interface SimilarRfi {
  rfi_id: UUID;
  number?: string | null;
  subject: string;
  status: string;
  distance: number;
  created_at: ISODate;
}

export interface RfiSimilarResponse {
  source_rfi_id: UUID;
  results: SimilarRfi[];
  embedding_model?: string | null;
}

export interface RfiCitation {
  document_id: UUID;
  chunk_id: UUID;
  page_number?: number | null;
  snippet: string;
  drawing_number?: string | null;
  discipline?: string | null;
}

export interface RfiResponseDraft {
  id: UUID;
  organization_id: UUID;
  rfi_id: UUID;
  draft_text: string;
  citations: RfiCitation[];
  model_version: string;
  generated_at: ISODate;
  accepted_at?: ISODate | null;
  accepted_by?: UUID | null;
  notes?: string | null;
}
