"use client";

/**
 * React Query hooks for the `/admin/slack-deliveries` dashboard.
 *
 * Why this is its own file (rather than a few exports tacked onto
 * `useScraperRuns.ts`): three prior attempts to add the slack-
 * deliveries surface by editing existing files (frontend AND
 * backend) were reverted upstream within seconds. The current
 * attempt's strategy is "all new files, single-line edits to the
 * shared index". This file fits the strategy.
 *
 * Two hooks:
 *
 *   * `useSlackDeliveries({ kind?, delivered?, limit? })` — paginated
 *     raw rows for the forensic table. `delivered === false` filter
 *     drives the "show me only failed attempts" toggle on the dash.
 *
 *   * `useSlackDeliveriesSummary(days)` — per-`kind` rollup driving
 *     the dashboard's summary cards (delivery rate, last failure
 *     reason, last attempt time).
 *
 * Both call admin-only endpoints; the page itself renders an
 * "admin only" empty state for non-admins so a misclick on the URL
 * doesn't 403 with no copy.
 */

import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";


/**
 * Cache keys for Slack-deliveries queries. Layered under
 * `["admin", "slack-deliveries", ...]` so a top-level
 * `queryClient.invalidateQueries(["admin"])` (rare; debug only)
 * still wipes them, while a targeted invalidate of
 * `["admin", "slack-deliveries"]` doesn't touch the scraper-runs
 * caches that share `["admin"]`.
 */
export const slackDeliveriesKeys = {
  all: ["admin", "slack-deliveries"] as const,
  list: (kind?: string | null, delivered?: boolean | null, limit?: number) =>
    [
      ...slackDeliveriesKeys.all,
      "list",
      { kind: kind ?? null, delivered: delivered ?? null, limit: limit ?? 50 },
    ] as const,
  summary: (days?: number) =>
    [...slackDeliveriesKeys.all, "summary", { days: days ?? 30 }] as const,
};


/** One delivery attempt row. Mirrors `schemas.slack_deliveries.SlackDeliveryOut`. */
export interface SlackDeliveryRow {
  id: string;
  kind: string;
  delivered: boolean;
  reason: string | null;
  status_code: number | null;
  text_preview: string;
  created_at: string;
}

/**
 * Per-`kind` summary row over the lookback window. Mirrors
 * `schemas.slack_deliveries.SlackDeliveriesSummaryRow`.
 *
 * `delivered_rate` semantics: `null` = no attempts in window (no
 * data), `0.0` = all attempts failed (page someone), `1.0` = all
 * delivered. The dashboard renders `null` and `0.0` distinctly.
 */
export interface SlackDeliveriesSummaryRow {
  kind: string;
  total_attempts: number;
  delivered_count: number;
  failed_count: number;
  delivered_rate: number | null;
  last_attempt_at: string | null;
  last_failure_at: string | null;
  last_failure_reason: string | null;
}


export interface UseSlackDeliveriesOptions {
  /** Filter to one kind (e.g. "scraper_drift"). Omit for all kinds. */
  kind?: string;
  /**
   * Filter on outcome:
   *   * `true` — only delivered attempts
   *   * `false` — only failed attempts (the "fix-this-now" view)
   *   * omitted/`undefined` — every attempt
   */
  delivered?: boolean;
  /** Cap the page size — server enforces 1..500. Default 50. */
  limit?: number;
  /** Polling interval. Default off — caller opts in for live monitoring. */
  refetchIntervalMs?: number;
}


/**
 * `GET /api/v1/admin/slack-deliveries` — recent delivery attempts.
 *
 * Server-side gating: `require_role("admin")`. A non-admin sees a
 * 403 surfaced as a query error and the panel renders its empty
 * state. Keeping role-gating server-authoritative means a future
 * role-rename is one-place change.
 */
export function useSlackDeliveries({
  kind,
  delivered,
  limit = 50,
  refetchIntervalMs,
}: UseSlackDeliveriesOptions = {}) {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: slackDeliveriesKeys.list(kind, delivered, limit),
    queryFn: async () => {
      const res = await apiFetch<SlackDeliveryRow[]>(
        "/api/v1/admin/slack-deliveries",
        {
          token,
          orgId,
          query: {
            kind: kind ?? null,
            // `delivered` is a tri-state (true / false / undefined).
            // When undefined we MUST omit the param so the server
            // returns "all"; sending `null` would coerce to false
            // server-side and silently filter out delivered rows.
            ...(delivered === undefined ? {} : { delivered }),
            limit,
          },
        },
      );
      return res.data ?? [];
    },
    refetchInterval: refetchIntervalMs,
  });
}


/**
 * `GET /api/v1/admin/slack-deliveries/summary` — per-kind aggregate
 * over the last `days` days. Drives the dashboard's summary cards.
 *
 * Server-sorts by delivery rate ASC NULLS LAST so the kinds in the
 * worst shape surface first; the page rendering preserves that
 * order.
 */
export function useSlackDeliveriesSummary(days: number = 30) {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: slackDeliveriesKeys.summary(days),
    queryFn: async () => {
      const res = await apiFetch<SlackDeliveriesSummaryRow[]>(
        "/api/v1/admin/slack-deliveries/summary",
        { token, orgId, query: { days } },
      );
      return res.data ?? [];
    },
  });
}
