"use client";

import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";
import type {
  Conflict,
  ConflictScanResponse,
  ConflictSeverity,
  ConflictStatus,
  ConflictType,
  ConflictWithExcerpts,
} from "@aec/ui/drawbridge";

import { drawbridgeKeys } from "./keys";

export interface ConflictFilters {
  project_id: string;
  status?: ConflictStatus;
  severity?: ConflictSeverity;
  conflict_type?: ConflictType;
  limit?: number;
  offset?: number;
}

export function useConflicts(filters: ConflictFilters) {
  const { token, orgId } = useSession();
  return useQuery({
    enabled: Boolean(filters.project_id),
    queryKey: drawbridgeKeys.conflicts(filters),
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const res = await apiFetch<ConflictWithExcerpts[]>("/api/v1/drawbridge/conflicts", {
        method: "GET",
        token,
        orgId,
        query: {
          project_id: filters.project_id,
          status: filters.status,
          severity: filters.severity,
          conflict_type: filters.conflict_type,
          limit: filters.limit ?? 50,
          offset: filters.offset ?? 0,
        },
      });
      return { data: (res.data ?? []) as ConflictWithExcerpts[], meta: res.meta };
    },
  });
}

export function useConflict(id: string | undefined) {
  const { token, orgId } = useSession();
  return useQuery({
    enabled: Boolean(id),
    queryKey: id ? drawbridgeKeys.conflict(id) : ["noop"],
    queryFn: async () => {
      const res = await apiFetch<ConflictWithExcerpts>(`/api/v1/drawbridge/conflicts/${id}`, {
        method: "GET",
        token,
        orgId,
      });
      return res.data as ConflictWithExcerpts;
    },
  });
}

export function useConflictScan() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationKey: ["drawbridge", "conflict-scan"],
    mutationFn: async (payload: {
      project_id: string;
      document_ids?: string[];
      severities?: ConflictSeverity[];
    }) => {
      const res = await apiFetch<ConflictScanResponse>("/api/v1/drawbridge/conflict-scan", {
        method: "POST",
        token,
        orgId,
        body: payload,
      });
      return res.data as ConflictScanResponse;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: drawbridgeKeys.all });
    },
  });
}

export function useUpdateConflict() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationKey: ["drawbridge", "conflict-update"],
    mutationFn: async ({
      id,
      status,
      resolution_notes,
    }: {
      id: string;
      status?: ConflictStatus;
      resolution_notes?: string;
    }) => {
      const res = await apiFetch<Conflict>(`/api/v1/drawbridge/conflicts/${id}`, {
        method: "PATCH",
        token,
        orgId,
        body: { status, resolution_notes },
      });
      return res.data as Conflict;
    },
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: drawbridgeKeys.all });
      qc.invalidateQueries({ queryKey: drawbridgeKeys.conflict(data.id) });
    },
  });
}
