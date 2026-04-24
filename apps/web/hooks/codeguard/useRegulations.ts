"use client";

import { useQuery, keepPreviousData } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";
import type {
  RegulationCategory,
  RegulationSummary,
} from "@aec/ui/codeguard";
import { codeguardKeys } from "./keys";

export interface RegulationFilters {
  country_code?: string;
  jurisdiction?: string;
  category?: RegulationCategory;
  q?: string;
  limit?: number;
  offset?: number;
}

export interface RegulationSection {
  section_ref: string;
  title?: string | null;
  content: string;
}

export interface RegulationDetail extends RegulationSummary {
  content: Record<string, unknown> | null;
  sections: RegulationSection[];
}

export function useRegulations(filters: RegulationFilters = {}) {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: codeguardKeys.regulations(filters),
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const res = await apiFetch<RegulationSummary[]>(
        "/api/v1/codeguard/regulations",
        {
          method: "GET",
          token,
          orgId,
          query: {
            country_code: filters.country_code,
            jurisdiction: filters.jurisdiction,
            category: filters.category,
            q: filters.q,
            limit: filters.limit ?? 20,
            offset: filters.offset ?? 0,
          },
        },
      );
      return { data: (res.data ?? []) as RegulationSummary[], meta: res.meta };
    },
  });
}

export function useRegulation(id: string | undefined) {
  const { token, orgId } = useSession();
  return useQuery({
    enabled: Boolean(id),
    queryKey: id ? codeguardKeys.regulation(id) : ["noop"],
    queryFn: async () => {
      const res = await apiFetch<RegulationDetail>(
        `/api/v1/codeguard/regulations/${id}`,
        { method: "GET", token, orgId },
      );
      return res.data as RegulationDetail;
    },
  });
}
