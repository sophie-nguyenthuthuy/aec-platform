"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type {
  AiEstimateResult,
  EstimateDetail,
  EstimateFromBriefInput,
  EstimateFromDrawingsInput,
  EstimateStatus,
  EstimateSummary,
  UUID,
} from "@aec/types";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";

export const costpulseKeys = {
  all: ["costpulse"] as const,
  estimates: () => [...costpulseKeys.all, "estimates"] as const,
  estimatesList: (filters: EstimateListFilters) =>
    [...costpulseKeys.estimates(), "list", filters] as const,
  estimateDetail: (id: UUID) => [...costpulseKeys.estimates(), "detail", id] as const,
  prices: () => [...costpulseKeys.all, "prices"] as const,
  priceHistory: (code: string, province?: string | null) =>
    [...costpulseKeys.prices(), "history", code, province ?? null] as const,
  suppliers: () => [...costpulseKeys.all, "suppliers"] as const,
  rfq: () => [...costpulseKeys.all, "rfq"] as const,
  benchmark: () => [...costpulseKeys.all, "benchmark"] as const,
};

export interface EstimateListFilters {
  project_id?: UUID;
  status?: EstimateStatus;
  page?: number;
  per_page?: number;
}

export function useEstimates(filters: EstimateListFilters = {}) {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: costpulseKeys.estimatesList(filters),
    queryFn: async () => {
      const res = await apiFetch<EstimateSummary[]>("/api/v1/costpulse/estimates", {
        token,
        orgId,
        query: {
          project_id: filters.project_id ?? null,
          status: filters.status ?? null,
          page: filters.page ?? 1,
          per_page: filters.per_page ?? 20,
        },
      });
      return { items: res.data ?? [], meta: res.meta };
    },
  });
}

export function useEstimate(id: UUID | null) {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: costpulseKeys.estimateDetail(id ?? ("" as UUID)),
    enabled: Boolean(id),
    queryFn: async () => {
      const res = await apiFetch<EstimateDetail>(`/api/v1/costpulse/estimates/${id}`, {
        token,
        orgId,
      });
      if (!res.data) throw new Error("Estimate not found");
      return res.data;
    },
  });
}

export function useEstimateFromBrief() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (input: EstimateFromBriefInput) => {
      const res = await apiFetch<AiEstimateResult>("/api/v1/costpulse/estimate/from-brief", {
        method: "POST",
        body: input,
        token,
        orgId,
      });
      if (!res.data) throw new Error("Empty response");
      return res.data;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: costpulseKeys.estimates() });
    },
  });
}

export function useEstimateFromDrawings() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (input: EstimateFromDrawingsInput) => {
      const res = await apiFetch<AiEstimateResult>("/api/v1/costpulse/estimate/from-drawings", {
        method: "POST",
        body: input,
        token,
        orgId,
      });
      if (!res.data) throw new Error("Empty response");
      return res.data;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: costpulseKeys.estimates() });
    },
  });
}

export function useUpdateBoq(estimateId: UUID) {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (items: EstimateDetail["items"]) => {
      const res = await apiFetch<EstimateDetail>(
        `/api/v1/costpulse/estimates/${estimateId}/boq`,
        {
          method: "PUT",
          body: { items, recompute_totals: true },
          token,
          orgId,
        },
      );
      if (!res.data) throw new Error("Empty response");
      return res.data;
    },
    onSuccess: (data) => {
      qc.setQueryData(costpulseKeys.estimateDetail(estimateId), data);
      void qc.invalidateQueries({ queryKey: costpulseKeys.estimates() });
    },
  });
}

export function useApproveEstimate(estimateId: UUID) {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const res = await apiFetch<EstimateSummary>(
        `/api/v1/costpulse/estimates/${estimateId}/approve`,
        { method: "POST", token, orgId },
      );
      return res.data;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: costpulseKeys.estimates() });
      void qc.invalidateQueries({ queryKey: costpulseKeys.estimateDetail(estimateId) });
    },
  });
}
