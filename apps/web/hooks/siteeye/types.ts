// Re-export the shared UI types and add hook-specific filter shapes.
export type {
  ConstructionPhase,
  Envelope,
  EnvelopeMeta,
  GeoLocation,
  IncidentSeverity,
  IncidentStatus,
  IncidentType,
  PhotoAIAnalysis,
  PhotoBatchUploadRequest,
  PhotoBatchUploadResponse,
  PhotoDetection,
  PhotoUploadItem,
  ProgressSnapshot,
  ProgressTimeline,
  ReportContent,
  ReportKPIs,
  SafetyIncident,
  SafetyStatus,
  ScheduleStatus,
  SitePhoto,
  SiteVisit,
  SiteVisitCreate,
  UUID,
  WeeklyReport,
} from "@aec/ui/siteeye/types";

import type { IncidentSeverity, IncidentStatus, IncidentType, SafetyStatus, UUID } from "@aec/ui/siteeye/types";

export interface VisitListFilters {
  project_id?: UUID;
  date_from?: string;
  date_to?: string;
  limit?: number;
  offset?: number;
}

export interface PhotoListFilters {
  project_id?: UUID;
  site_visit_id?: UUID;
  tags?: string[];
  safety_status?: SafetyStatus;
  date_from?: string;
  date_to?: string;
  limit?: number;
  offset?: number;
}

export interface SafetyIncidentFilters {
  project_id?: UUID;
  status?: IncidentStatus;
  severity?: IncidentSeverity;
  incident_type?: IncidentType;
  date_from?: string;
  date_to?: string;
  limit?: number;
  offset?: number;
}

export interface WeeklyReportListFilters {
  project_id?: UUID;
  limit?: number;
  offset?: number;
}
