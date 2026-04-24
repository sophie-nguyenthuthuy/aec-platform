"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";
import type { AsBuiltDrawing, Discipline } from "@aec/ui/handover";
import { handoverKeys } from "./keys";

export interface RegisterAsBuiltRequest {
  project_id: string;
  package_id?: string;
  drawing_code: string;
  discipline: Discipline;
  title: string;
  file_id: string;
  change_note?: string;
}

export function useProjectAsBuilts(
  projectId: string | undefined,
  discipline?: Discipline,
) {
  const { token, orgId } = useSession();
  return useQuery({
    enabled: Boolean(projectId),
    queryKey: projectId
      ? handoverKeys.asBuilts(projectId, discipline)
      : ["noop"],
    queryFn: async () => {
      const res = await apiFetch<AsBuiltDrawing[]>(
        `/api/v1/handover/projects/${projectId}/as-builts`,
        {
          method: "GET",
          token,
          orgId,
          query: { discipline },
        },
      );
      return res.data as AsBuiltDrawing[];
    },
  });
}

export function useRegisterAsBuilt() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationKey: ["handover", "as-builts", "register"],
    mutationFn: async (payload: RegisterAsBuiltRequest) => {
      const res = await apiFetch<AsBuiltDrawing>("/api/v1/handover/as-builts", {
        method: "POST",
        token,
        orgId,
        body: payload,
      });
      return res.data as AsBuiltDrawing;
    },
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({
        queryKey: ["handover", "as-builts", vars.project_id],
      });
    },
  });
}
