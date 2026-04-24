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
import type { SafetyIncident, SafetyIncidentFilters, UUID } from "./types";

export function useSafetyIncidents(filters: SafetyIncidentFilters = {}) {
  const { token } = useSession();
  return useQuery({
    queryKey: siteeyeKeys.safety(filters),
    queryFn: () =>
      apiRequestWithMeta<SafetyIncident[]>("/api/v1/siteeye/safety-incidents", {
        params: serialize(filters),
        token,
      }),
    placeholderData: keepPreviousData,
  });
}

export function useAcknowledgeIncident() {
  const { token } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      resolve,
      notes,
    }: {
      id: UUID;
      resolve?: boolean;
      notes?: string;
    }) =>
      apiRequest<SafetyIncident>(
        `/api/v1/siteeye/safety-incidents/${id}/ack`,
        {
          method: "PATCH",
          body: { resolve: Boolean(resolve), notes },
          token,
        },
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: siteeyeKeys.all });
    },
  });
}

function serialize(f: SafetyIncidentFilters): Record<string, string | number> {
  const out: Record<string, string | number> = {};
  if (f.project_id) out.project_id = f.project_id;
  if (f.status) out.status = f.status;
  if (f.severity) out.severity = f.severity;
  if (f.incident_type) out.incident_type = f.incident_type;
  if (f.date_from) out.date_from = f.date_from;
  if (f.date_to) out.date_to = f.date_to;
  if (f.limit !== undefined) out.limit = f.limit;
  if (f.offset !== undefined) out.offset = f.offset;
  return out;
}
