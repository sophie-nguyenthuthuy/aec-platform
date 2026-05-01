"use client";

import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";

export interface QuotaDimension {
  used: number;
  limit: number | null;
  /** Percent of cap (0-100, one decimal). null when limit is null
   *  (unlimited on this dimension) — banner consumes null as "don't
   *  render this dimension's bar." */
  percent: number | null;
}

export interface CodeguardQuota {
  organization_id: string;
  /** True when the org has no quota row at all. Banner short-circuits
   *  to render nothing in this case rather than interpreting null
   *  percents per dimension. */
  unlimited: boolean;
  input: QuotaDimension | null;
  output: QuotaDimension | null;
  period_start: string | null;
}

/** Fetch the caller's org's quota state.
 *
 * The banner refreshes on every codeguard page mount + every 60s while
 * the page is visible — frequent enough that a user crossing the 95%
 * threshold mid-session sees the red treatment within one tick, but
 * not so frequent that the route becomes a dashboard burden. The refresh
 * is cheap (single PK lookup + a LEFT JOIN) so the cadence is bounded
 * by user-perceived latency, not DB load. */
export function useCodeguardQuota() {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: ["codeguard", "quota", orgId],
    // 60s refetch — low enough that a user spending heavily sees the
    // transition into yellow/red within one tick. Disabled when the
    // page is hidden so background tabs don't poll forever.
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
    queryFn: async () => {
      const res = await apiFetch<CodeguardQuota>("/api/v1/codeguard/quota", {
        method: "GET",
        token,
        orgId,
      });
      return res.data as CodeguardQuota;
    },
  });
}
