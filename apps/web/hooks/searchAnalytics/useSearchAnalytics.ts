"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";
import type { ISODate } from "@aec/types/envelope";


// ---------- Response shape ----------
//
// Mirrors the payload returned by `GET /api/v1/search/analytics`. Kept
// in this file (not in `@aec/types`) because the analytics page is the
// only consumer — promote later if a second component needs it.

export interface SearchAnalyticsTotals {
  total_searches: number;
  empty_searches: number;
  unique_users: number;
}

export interface TopQueryRow {
  query: string;
  run_count: number;
  avg_results: number;
  empty_count: number;
}

export interface NoResultQueryRow {
  query: string;
  run_count: number;
  last_run: ISODate | null;
}

export interface ScopeDistributionRow {
  scope: string;
  run_count: number;
}

export interface MatchedDistributionRow {
  label: string;
  run_count: number;
}

export interface SearchAnalytics {
  window_days: number;
  totals: SearchAnalyticsTotals;
  top_queries: TopQueryRow[];
  no_result_queries: NoResultQueryRow[];
  scope_distribution: ScopeDistributionRow[];
  matched_distribution: MatchedDistributionRow[];
}

export interface SearchAnalyticsFilters {
  days?: number;
  top_n?: number;
}

const analyticsKey = (filters: SearchAnalyticsFilters) =>
  ["search", "analytics", filters] as const;


/**
 * Admin-only telemetry view. Returns 403 for non-admins — the calling
 * page should render a friendly hint when `isError` fires.
 *
 * `keepPreviousData` so the window-toggle (7d / 30d / 90d) doesn't
 * flash a loader between values; the prior breakdown stays visible
 * while the new one fetches.
 */
export function useSearchAnalytics(filters: SearchAnalyticsFilters = {}) {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: analyticsKey(filters),
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const res = await apiFetch<SearchAnalytics>("/api/v1/search/analytics", {
        method: "GET",
        token,
        orgId,
        query: {
          days: filters.days ?? 30,
          top_n: filters.top_n ?? 20,
        },
      });
      return res.data as SearchAnalytics;
    },
  });
}
