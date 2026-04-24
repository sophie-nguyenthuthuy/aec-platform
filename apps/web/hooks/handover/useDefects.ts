"use client";

import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";
import type { Defect, DefectPriority, DefectStatus } from "@aec/ui/handover";
import { handoverKeys } from "./keys";

export interface DefectListFilters {
  project_id?: string;
  package_id?: string;
  status?: DefectStatus;
  priority?: DefectPriority;
  assignee_id?: string;
  limit?: number;
  offset?: number;
}

export interface CreateDefectRequest {
  project_id: string;
  package_id?: string;
  title: string;
  description?: string;
  location?: Record<string, unknown>;
  photo_file_ids?: string[];
  priority?: DefectPriority;
  assignee_id?: string;
}

export interface UpdateDefectRequest {
  status?: DefectStatus;
  priority?: DefectPriority;
  assignee_id?: string;
  description?: string;
  location?: Record<string, unknown>;
  photo_file_ids?: string[];
  resolution_notes?: string;
}

export function useDefects(filters: DefectListFilters = {}) {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: handoverKeys.defects(filters),
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const res = await apiFetch<Defect[]>("/api/v1/handover/defects", {
        method: "GET",
        token,
        orgId,
        query: {
          project_id: filters.project_id,
          package_id: filters.package_id,
          status: filters.status,
          priority: filters.priority,
          assignee_id: filters.assignee_id,
          limit: filters.limit ?? 50,
          offset: filters.offset ?? 0,
        },
      });
      return { data: (res.data ?? []) as Defect[], meta: res.meta };
    },
  });
}

export function useCreateDefect() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationKey: ["handover", "defects", "create"],
    mutationFn: async (payload: CreateDefectRequest) => {
      const res = await apiFetch<Defect>("/api/v1/handover/defects", {
        method: "POST",
        token,
        orgId,
        body: payload,
      });
      return res.data as Defect;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["handover", "defects"] });
    },
  });
}

export function useUpdateDefect() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationKey: ["handover", "defects", "update"],
    mutationFn: async (args: { id: string; patch: UpdateDefectRequest }) => {
      const res = await apiFetch<Defect>(
        `/api/v1/handover/defects/${args.id}`,
        { method: "PATCH", token, orgId, body: args.patch },
      );
      return res.data as Defect;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["handover", "defects"] });
    },
  });
}
