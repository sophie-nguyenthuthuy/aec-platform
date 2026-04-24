"use client";
import { useQuery } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";
import { useSession } from "@/lib/auth-context";
import { siteeyeKeys } from "./keys";
import type { ProgressTimeline, UUID } from "./types";

export function useProgressTimeline(
  projectId: UUID | undefined,
  opts: { dateFrom?: string; dateTo?: string } = {},
) {
  const { token } = useSession();
  return useQuery({
    enabled: Boolean(projectId),
    queryKey: siteeyeKeys.progress(projectId ?? "", opts.dateFrom, opts.dateTo),
    queryFn: () =>
      apiRequest<ProgressTimeline>("/api/v1/siteeye/progress", {
        params: {
          project_id: projectId ?? null,
          date_from: opts.dateFrom,
          date_to: opts.dateTo,
        },
        token,
      }),
  });
}
