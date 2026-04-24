"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { MaterialCategory, MaterialPrice, PriceHistory } from "@aec/types";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";

import { costpulseKeys } from "./useEstimates";

export interface PriceFilters {
  q?: string;
  material_code?: string;
  category?: MaterialCategory;
  province?: string;
  as_of?: string;
  limit?: number;
  offset?: number;
}

export function usePrices(filters: PriceFilters = {}) {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: [...costpulseKeys.prices(), "list", filters] as const,
    queryFn: async () => {
      const res = await apiFetch<MaterialPrice[]>("/api/v1/costpulse/prices", {
        token,
        orgId,
        query: {
          q: filters.q ?? null,
          material_code: filters.material_code ?? null,
          category: filters.category ?? null,
          province: filters.province ?? null,
          as_of: filters.as_of ?? null,
          limit: filters.limit ?? 50,
          offset: filters.offset ?? 0,
        },
      });
      return { items: res.data ?? [], meta: res.meta };
    },
  });
}

export function usePriceHistory(materialCode: string | null, province?: string | null) {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: costpulseKeys.priceHistory(materialCode ?? "", province ?? null),
    enabled: Boolean(materialCode),
    queryFn: async () => {
      const res = await apiFetch<PriceHistory>(
        `/api/v1/costpulse/prices/history/${materialCode}`,
        { token, orgId, query: { province: province ?? null } },
      );
      if (!res.data) throw new Error("No history");
      return res.data;
    },
  });
}

export interface PriceOverrideInput {
  material_code: string;
  price_vnd: number;
  province: string;
  name?: string;
  unit?: string;
  category?: MaterialCategory;
}

export function usePriceOverride() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (input: PriceOverrideInput) => {
      const res = await apiFetch<MaterialPrice>("/api/v1/costpulse/prices/override", {
        method: "POST",
        token,
        orgId,
        query: {
          material_code: input.material_code,
          price_vnd: input.price_vnd,
          province: input.province,
          name: input.name ?? null,
          unit: input.unit ?? null,
          category: input.category ?? null,
        },
      });
      return res.data;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: costpulseKeys.prices() });
    },
  });
}

export function usePriceAlert() {
  const { token, orgId } = useSession();
  return useMutation({
    mutationFn: async (input: { material_code: string; province?: string; threshold_pct?: number }) => {
      const res = await apiFetch<{ id: string; material_code: string }>(
        "/api/v1/costpulse/price-alerts",
        {
          method: "POST",
          token,
          orgId,
          query: {
            material_code: input.material_code,
            province: input.province ?? null,
            threshold_pct: input.threshold_pct ?? 5,
          },
        },
      );
      return res.data;
    },
  });
}
