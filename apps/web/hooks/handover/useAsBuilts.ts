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

// ---- DRAWBRIDGE → HANDOVER bulk promotion -----------------------------------

export interface PromotedDrawingSummary {
  drawing_code: string;
  action: "created" | "versioned" | "skipped";
  current_version?: number | null;
  reason?: string | null;
}

export interface PromoteDrawingsResponse {
  package_id: string;
  project_id: string;
  documents_considered: number;
  promoted: PromotedDrawingSummary[];
}

export interface PromoteDrawingsRequest {
  /** ISO discipline code (architecture / structure / mep / ...). Optional —
   *  omit to sweep across all disciplines. */
  discipline?: string;
  /** ILIKE filter on the drawbridge `drawing_number` (e.g. "A-%"). */
  drawing_number_like?: string;
}

/** Sweep DRAWBRIDGE's `documents` table for the package's project and promote
 *  the latest-revision drawing of each `drawing_number` into an as-built. The
 *  endpoint is idempotent — re-running creates nothing if the latest file
 *  was already registered. */
export function usePromoteDrawings(packageId: string) {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationKey: ["handover", "packages", packageId, "promote-drawings"],
    mutationFn: async (payload: PromoteDrawingsRequest = {}) => {
      const res = await apiFetch<PromoteDrawingsResponse>(
        `/api/v1/handover/packages/${packageId}/promote-drawings`,
        { method: "POST", token, orgId, body: payload },
      );
      return res.data as PromoteDrawingsResponse;
    },
    onSuccess: (data) => {
      // Refresh the project's as-built list so the new versions show up.
      qc.invalidateQueries({
        queryKey: ["handover", "as-builts", data.project_id],
      });
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
