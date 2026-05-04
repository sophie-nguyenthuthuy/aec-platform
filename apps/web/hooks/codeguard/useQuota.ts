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


// ---------- Quota history (recent-usage trend) -------------------------

export interface QuotaHistoryEntry {
  /** First-of-month ISO date (e.g. "2026-05-01"). */
  period_start: string;
  input_tokens: number;
  output_tokens: number;
}

export interface CodeguardQuotaHistory {
  organization_id: string;
  /** Window size requested + clamped (server-side: 1..12). The UI
   *  reads this back so it can render N bars even for months with
   *  no usage row (missing months render as zero-width — see route
   *  docstring for the "nothing happened ≠ no data" rationale). */
  months: number;
  input_limit: number | null;
  output_limit: number | null;
  /** Most-recent first. Months with no recorded usage are absent. */
  history: QuotaHistoryEntry[];
}

/** Fetch the caller's org's last N months of usage for the
 *  `/codeguard/quota` trend strip. Default 3 months matches the page
 *  copy ("3 tháng gần nhất"); the backend caps at 12.
 *
 *  Different cadence than `useCodeguardQuota`: history changes only at
 *  month rollover or after a `quotas reset`, neither of which warrants
 *  per-minute polling. Refresh on page focus + a 5-minute stale window
 *  is plenty. */
export function useCodeguardQuotaHistory(months = 3) {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: ["codeguard", "quota", "history", orgId, months],
    // 5min staleness — history doesn't change minute-to-minute.
    staleTime: 5 * 60_000,
    queryFn: async () => {
      const res = await apiFetch<CodeguardQuotaHistory>(
        `/api/v1/codeguard/quota/history?months=${months}`,
        { method: "GET", token, orgId },
      );
      return res.data as CodeguardQuotaHistory;
    },
  });
}


// ---------- Audit log (tenant-facing) ---------------------------------

export interface QuotaAuditEntry {
  id: string;
  occurred_at: string | null;
  actor: string | null;
  action: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  /** Pre-rendered diff summary, vi-VN dot grouping. */
  summary: string;
}

export interface CodeguardQuotaAudit {
  organization_id: string;
  limit: number;
  entries: QuotaAuditEntry[];
  /** Cursor for the next page. Format `<iso_ts>:<uuid>`. Null
   *  means "you've reached the end" — page should stop fetching.
   *  Present only when the response returned exactly `limit` rows
   *  (which signals "there might be more"); a result set smaller
   *  than `limit` returns `next_cursor=null`. */
  next_cursor: string | null;
}

export interface QuotaAuditFilters {
  limit?: number;
  since?: string;
  /** `quota_reconcile` is emitted by the reconcile cron's
   *  remediation path (`scripts/codeguard_quotas.py reconcile
   *  --remediate`). Tenant admins investigating a cap-cache
   *  realignment can filter to just those entries. */
  action?: "quota_set" | "quota_reset" | "quota_reconcile";
  /** Cursor from a prior response's `next_cursor`. When set, the
   *  server returns rows STRICTLY older than this position. */
  before?: string;
}

/** Fetch the caller's org's quota-mutation audit log. */
export function useCodeguardQuotaAudit(filters: QuotaAuditFilters = {}) {
  const { token, orgId } = useSession();
  const limit = filters.limit ?? 50;
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  if (filters.since) params.set("since", filters.since);
  if (filters.action) params.set("action", filters.action);
  if (filters.before) params.set("before", filters.before);

  return useQuery({
    queryKey: [
      "codeguard",
      "quota",
      "audit",
      orgId,
      limit,
      filters.since,
      filters.action,
      filters.before,
    ],
    staleTime: 30_000,
    queryFn: async () => {
      const res = await apiFetch<CodeguardQuotaAudit>(
        `/api/v1/codeguard/quota/audit?${params.toString()}`,
        { method: "GET", token, orgId },
      );
      return res.data as CodeguardQuotaAudit;
    },
  });
}


// ---------- Top users (per-user spend ranking) -------------------------

export interface QuotaTopUser {
  user_id: string;
  /** May be empty string if the user was deleted between recording the
   *  spend and rendering the row — the LEFT JOIN preserves the
   *  attribution but loses the email when CASCADE has wiped the user. */
  email: string;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
}

export interface CodeguardQuotaTopUsers {
  organization_id: string;
  /** Server-clamped (1..50). UI reads this back to render the right
   *  number of rows even when the request asked for more than the
   *  server allowed. */
  limit: number;
  /** Sorted by total_tokens DESC, ties broken by user_id for stable
   *  rendering across refetches. */
  users: QuotaTopUser[];
}

/** Fetch the caller's org's top token consumers for the CURRENT
 *  period. Sits next to `useCodeguardQuota` on the quota page. 60s
 *  staleness — top-users only changes when an LLM call lands. */
export function useCodeguardQuotaTopUsers(limit = 10) {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: ["codeguard", "quota", "top-users", orgId, limit],
    staleTime: 60_000,
    queryFn: async () => {
      const res = await apiFetch<CodeguardQuotaTopUsers>(
        `/api/v1/codeguard/quota/top-users?limit=${limit}`,
        { method: "GET", token, orgId },
      );
      return res.data as CodeguardQuotaTopUsers;
    },
  });
}
