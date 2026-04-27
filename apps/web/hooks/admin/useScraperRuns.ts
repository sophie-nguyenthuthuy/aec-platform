"use client";
import { useQuery } from "@tanstack/react-query";
import type { ScraperRun } from "@aec/types";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";

export const adminKeys = {
  all: ["admin"] as const,
  scraperRuns: (slug?: string, limit?: number) =>
    [...adminKeys.all, "scraper-runs", { slug: slug ?? null, limit: limit ?? 20 }] as const,
};

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
