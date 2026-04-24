"use client";
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { apiRequest, apiRequestWithMeta } from "@/lib/api-client";
import { useSession } from "@/lib/auth-context";
import { siteeyeKeys } from "./keys";
import type { UUID, WeeklyReport, WeeklyReportListFilters } from "./types";

export function useReports(filters: WeeklyReportListFilters = {}) {
  const { token } = useSession();
  return useQuery({
    queryKey: siteeyeKeys.reports(filters),
    queryFn: () =>
      apiRequestWithMeta<WeeklyReport[]>("/api/v1/siteeye/reports", {
        params: serialize(filters),
        token,
      }),
    placeholderData: keepPreviousData,
  });
}

export function useGenerateReport() {
  const { token } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { project_id: UUID; week_start: string; week_end: string }) =>
      apiRequest<WeeklyReport>("/api/v1/siteeye/reports/generate", {
        method: "POST",
        body,
        token,
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: siteeyeKeys.all });
    },
  });
}

export function useSendReport() {
  const { token } = useSession();
  return useMutation({
    mutationFn: ({
      reportId,
      recipients,
      subject,
      message,
    }: {
      reportId: UUID;
      recipients: string[];
      subject?: string;
      message?: string;
    }) =>
      apiRequest<{ report_id: UUID; sent_to: string[]; sent_at: string }>(
        `/api/v1/siteeye/reports/${reportId}/send`,
        {
          method: "POST",
          body: { recipients, subject, message },
          token,
        },
      ),
  });
}

function serialize(f: WeeklyReportListFilters): Record<string, string | number> {
  const out: Record<string, string | number> = {};
  if (f.project_id) out.project_id = f.project_id;
  if (f.limit !== undefined) out.limit = f.limit;
  if (f.offset !== undefined) out.offset = f.offset;
  return out;
}
