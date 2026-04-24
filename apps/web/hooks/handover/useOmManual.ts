"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";
import type { Discipline, OmManual } from "@aec/ui/handover";
import { handoverKeys } from "./keys";

export interface GenerateOmManualRequest {
  project_id: string;
  package_id?: string;
  discipline?: Discipline;
  source_file_ids: string[];
  title?: string;
}

export function usePackageOmManuals(packageId: string | undefined) {
  const { token, orgId } = useSession();
  return useQuery({
    enabled: Boolean(packageId),
    queryKey: packageId ? handoverKeys.omManuals(packageId) : ["noop"],
    queryFn: async () => {
      const res = await apiFetch<OmManual[]>(
        `/api/v1/handover/packages/${packageId}/om-manuals`,
        { method: "GET", token, orgId },
      );
      return res.data as OmManual[];
    },
  });
}

export function useGenerateOmManual() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationKey: ["handover", "om-manuals", "generate"],
    mutationFn: async (payload: GenerateOmManualRequest) => {
      const res = await apiFetch<OmManual>(
        "/api/v1/handover/om-manuals/generate",
        { method: "POST", token, orgId, body: payload },
      );
      return res.data as OmManual;
    },
    onSuccess: (_data, vars) => {
      if (vars.package_id) {
        qc.invalidateQueries({
          queryKey: handoverKeys.omManuals(vars.package_id),
        });
      }
    },
  });
}
