import type {
  PhotoListFilters,
  SafetyIncidentFilters,
  VisitListFilters,
  WeeklyReportListFilters,
} from "./types";

// Centralised query keys so mutations can invalidate precisely.
export const siteeyeKeys = {
  all: ["siteeye"] as const,
  visits: (f?: VisitListFilters) =>
    ["siteeye", "visits", f ?? {}] as const,
  photos: (f?: PhotoListFilters) =>
    ["siteeye", "photos", f ?? {}] as const,
  progress: (projectId: string, dateFrom?: string, dateTo?: string) =>
    ["siteeye", "progress", projectId, dateFrom, dateTo] as const,
  safety: (f?: SafetyIncidentFilters) =>
    ["siteeye", "safety", f ?? {}] as const,
  reports: (f?: WeeklyReportListFilters) =>
    ["siteeye", "reports", f ?? {}] as const,
};
