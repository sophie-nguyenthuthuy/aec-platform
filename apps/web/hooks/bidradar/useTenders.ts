"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";
import type {
  ScoreMatchesResult,
  ScrapeResult,
  TenderDetail,
  TenderSource,
  TenderSummary,
} from "@aec/ui/bidradar";
import { bidradarKeys } from "./keys";

export interface TenderFilters {
  country_code?: string;
  province?: string;
  discipline?: string;
  min_budget_vnd?: number;
  max_budget_vnd?: number;
  deadline_before?: string;
  q?: string;
  limit?: number;
  offset?: number;
}

export function useTenders(filters: TenderFilters = {}) {
  const { token, orgId } = useSession();
  const query = { limit: 20, offset: 0, ...filters };
  return useQuery({
    queryKey: bidradarKeys.tenders(query),
    queryFn: async () => {
      const res = await apiFetch<TenderSummary[]>("/api/v1/bidradar/tenders", {
        method: "GET",
        query,
        token,
        orgId,
      });
      return {
        items: res.data ?? [],
        total: res.meta?.total ?? 0,
      };
    },
  });
}

export function useTender(tenderId: string | null) {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: bidradarKeys.tender(tenderId ?? ""),
    enabled: Boolean(tenderId),
    queryFn: async () => {
      const res = await apiFetch<TenderDetail>(`/api/v1/bidradar/tenders/${tenderId}`, {
        method: "GET",
        token,
        orgId,
      });
      return res.data!;
    },
  });
}

export function useTriggerScrape() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (args: { source: TenderSource; max_pages?: number }) => {
      const res = await apiFetch<ScrapeResult>("/api/v1/bidradar/scrape", {
        method: "POST",
        body: { source: args.source, max_pages: args.max_pages ?? 5 },
        token,
        orgId,
      });
      return res.data!;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: bidradarKeys.all });
    },
  });
}

export function useScoreMatches() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (args: { tender_ids?: string[]; rescore_existing?: boolean }) => {
      const res = await apiFetch<ScoreMatchesResult>("/api/v1/bidradar/score", {
        method: "POST",
        body: args,
        token,
        orgId,
      });
      return res.data!;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: bidradarKeys.all });
    },
  });
}
