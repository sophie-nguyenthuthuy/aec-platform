"use client";

import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";
import type { Rfi, RfiPriority, RfiStatus } from "@aec/ui/drawbridge";

import { drawbridgeKeys } from "./keys";

export interface RfiFilters {
  project_id: string;
  status?: RfiStatus;
  assigned_to?: string;
  priority?: RfiPriority;
  limit?: number;
  offset?: number;
}

export function useRFIs(filters: RfiFilters) {
  const { token, orgId } = useSession();
  return useQuery({
    enabled: Boolean(filters.project_id),
    queryKey: drawbridgeKeys.rfis(filters),
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const res = await apiFetch<Rfi[]>("/api/v1/drawbridge/rfis", {
        method: "GET",
        token,
        orgId,
        query: {
          project_id: filters.project_id,
          status: filters.status,
          assigned_to: filters.assigned_to,
          priority: filters.priority,
          limit: filters.limit ?? 50,
          offset: filters.offset ?? 0,
        },
      });
      return { data: (res.data ?? []) as Rfi[], meta: res.meta };
    },
  });
}

export interface CreateRfiInput {
  project_id: string;
  subject: string;
  description?: string;
  priority?: RfiPriority;
  due_date?: string;
  assigned_to?: string;
  related_document_ids?: string[];
  number?: string;
}

export function useCreateRFI() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationKey: ["drawbridge", "rfi-create"],
    mutationFn: async (payload: CreateRfiInput) => {
      const res = await apiFetch<Rfi>("/api/v1/drawbridge/rfis", {
        method: "POST",
        token,
        orgId,
        body: payload,
      });
      return res.data as Rfi;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: drawbridgeKeys.all });
    },
  });
}

export function useAnswerRFI() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationKey: ["drawbridge", "rfi-answer"],
    mutationFn: async ({
      id,
      response,
      close = true,
    }: {
      id: string;
      response: string;
      close?: boolean;
    }) => {
      const res = await apiFetch<Rfi>(`/api/v1/drawbridge/rfis/${id}/answer`, {
        method: "POST",
        token,
        orgId,
        body: { response, close },
      });
      return res.data as Rfi;
    },
    onSuccess: (rfi) => {
      qc.invalidateQueries({ queryKey: drawbridgeKeys.all });
      qc.setQueryData(drawbridgeKeys.rfi(rfi.id), rfi);
    },
  });
}

export function useGenerateRFI() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationKey: ["drawbridge", "rfi-generate"],
    mutationFn: async (payload: {
      conflict_id: string;
      assigned_to?: string;
      due_date?: string;
      priority?: RfiPriority;
    }) => {
      const res = await apiFetch<Rfi>("/api/v1/drawbridge/rfis/generate", {
        method: "POST",
        token,
        orgId,
        body: { priority: "high", ...payload },
      });
      return res.data as Rfi;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: drawbridgeKeys.all });
    },
  });
}
