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
import type { SiteVisit, SiteVisitCreate, VisitListFilters } from "./types";

export function useVisits(filters: VisitListFilters = {}) {
  const { token } = useSession();
  return useQuery({
    queryKey: siteeyeKeys.visits(filters),
    queryFn: () =>
      apiRequestWithMeta<SiteVisit[]>("/api/v1/siteeye/visits", {
        params: serialize(filters),
        token,
      }),
    placeholderData: keepPreviousData,
  });
}

export function useCreateVisit() {
  const { token } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: SiteVisitCreate) =>
      apiRequest<SiteVisit>("/api/v1/siteeye/visits", {
        method: "POST",
        body,
        token,
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: siteeyeKeys.all });
    },
  });
}

function serialize(f: VisitListFilters): Record<string, string | number> {
  const out: Record<string, string | number> = {};
  if (f.project_id) out.project_id = f.project_id;
  if (f.date_from) out.date_from = f.date_from;
  if (f.date_to) out.date_to = f.date_to;
  if (f.limit !== undefined) out.limit = f.limit;
  if (f.offset !== undefined) out.offset = f.offset;
  return out;
}
