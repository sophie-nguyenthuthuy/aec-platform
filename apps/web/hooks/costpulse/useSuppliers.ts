"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { Rfq, RfqInput, Supplier, UUID } from "@aec/types";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";

import { costpulseKeys } from "./useEstimates";

export interface SupplierFilters {
  category?: string;
  province?: string;
  verified_only?: boolean;
  q?: string;
  page?: number;
  per_page?: number;
}

export function useSuppliers(filters: SupplierFilters = {}) {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: [...costpulseKeys.suppliers(), "list", filters] as const,
    queryFn: async () => {
      const res = await apiFetch<Supplier[]>("/api/v1/costpulse/suppliers", {
        token,
        orgId,
        query: {
          category: filters.category ?? null,
          province: filters.province ?? null,
          verified_only: filters.verified_only ?? null,
          q: filters.q ?? null,
          page: filters.page ?? 1,
          per_page: filters.per_page ?? 20,
        },
      });
      return { items: res.data ?? [], meta: res.meta };
    },
  });
}

export function useRfqs(projectId?: UUID) {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: [...costpulseKeys.rfq(), "list", projectId ?? null] as const,
    queryFn: async () => {
      const res = await apiFetch<Rfq[]>("/api/v1/costpulse/rfq", {
        token,
        orgId,
        query: { project_id: projectId ?? null },
      });
      return res.data ?? [];
    },
  });
}

export function useCreateRfq() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (input: RfqInput) => {
      const res = await apiFetch<Rfq>("/api/v1/costpulse/rfq", {
        method: "POST",
        body: input,
        token,
        orgId,
      });
      if (!res.data) throw new Error("Empty response");
      return res.data;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: costpulseKeys.rfq() });
    },
  });
}
