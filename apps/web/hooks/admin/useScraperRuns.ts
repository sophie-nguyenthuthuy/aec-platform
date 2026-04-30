"use client";
import { useQuery } from "@tanstack/react-query";
import type { ScraperRun } from "@aec/types";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";

export const adminKeys = {
  all: ["admin"] as const,
  scraperRuns: (slug?: string, limit?: number) =>
    [...adminKeys.all, "scraper-runs", { slug: slug ?? null, limit: limit ?? 20 }] as const,
  scraperRunsSummary: (days?: number) =>
    [...adminKeys.all, "scraper-runs-summary", { days: days ?? 30 }] as const,
};


/**
 * Per-slug aggregate summary over a `days` window — drives the
 * `/admin/scrapers` dashboard. One row per slug with total_runs,
 * failure_rate, avg_drift, last_run_at, last_run_ok. Sorted by drift
 * DESC server-side so degraded slugs surface first.
 */
export interface ScraperRunsSummaryRow {
  slug: string;
  total_runs: number;
  failure_rate: number | null;
  avg_drift: number | null;
  last_run_at: string | null;
  last_run_ok: boolean | null;
}


export function useScraperRunsSummary(days: number = 30) {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: adminKeys.scraperRunsSummary(days),
    queryFn: async () => {
      const res = await apiFetch<ScraperRunsSummaryRow[]>(
        "/api/v1/admin/scraper-runs/summary",
        { token, orgId, query: { days } },
      );
      return res.data ?? [];
    },
  });
}

export interface UseScraperRunsOptions {
  /** Filter to a single scraper slug (e.g. "hanoi"). Omit for all slugs. */
  slug?: string;
  /** Cap the page size — server enforces 1..200. Default 20. */
  limit?: number;
  /** Polling interval. Default off — caller opts in for live monitoring. */
  refetchIntervalMs?: number;
}

/**
 * `GET /api/v1/admin/scraper-runs` — drift telemetry feed.
 *
 * Gated server-side by `admin` role. The hook itself doesn't check;
 * a non-admin caller will see the 403 surface as a query error and
 * the panel will render its empty state. Keeping role-gating server-
 * authoritative means a future role-rename is one-place change.
 */
export function useScraperRuns({ slug, limit = 20, refetchIntervalMs }: UseScraperRunsOptions = {}) {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: adminKeys.scraperRuns(slug, limit),
    queryFn: async () => {
      const res = await apiFetch<ScraperRun[]>("/api/v1/admin/scraper-runs", {
        token,
        orgId,
        query: { slug: slug ?? null, limit },
      });
      return res.data ?? [];
    },
    refetchInterval: refetchIntervalMs,
  });
}
