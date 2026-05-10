"use client";

/**
 * `GET /api/v1/admin/operational-health` (cycle S2).
 *
 * Returns four counts the dashboard inbox widget renders. Each count
 * is click-through to the corresponding admin page.
 *
 * Drives the "Operational health" widget at the top of `/inbox`.
 * Refetch every 60s — counts shift slowly (cron stuck flag updates
 * within the watchdog's 5-min cadence; unused-key threshold is 90d).
 *
 * Admin-only on the server side. Non-admins get a 403; the widget
 * renders nothing in that case rather than an error banner — the
 * inbox itself stays useful for the non-admin.
 */

import { useQuery } from "@tanstack/react-query";

import { ApiError, apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";


export interface OperationalHealthCounts {
  /** Active (non-revoked) API keys not used in 90+ days. Cycle Q3. */
  unused_api_keys: number;
  /** Cron runs in `running` status past 3× their rolling p95. Cycle N2. */
  stuck_crons: number;
  /** Async audit-export jobs in pending/running. Cycle Q1. */
  pending_audit_exports: number;
  /** Webhook subscriptions with `failure_count > 0`. Cycle O+. */
  failing_webhook_subscriptions: number;
}


export function useOperationalHealth() {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: ["admin", "operational-health"] as const,
    refetchInterval: 60_000,
    // Don't show the widget for non-admins — the API 403s and
    // useQuery normally surfaces that as isError. We treat 403 as
    // "no data" so the widget hides itself; other errors propagate.
    retry: (failureCount, err) => {
      if (err instanceof ApiError && err.status === 403) return false;
      return failureCount < 3;
    },
    queryFn: async () => {
      const res = await apiFetch<OperationalHealthCounts>(
        "/api/v1/admin/operational-health",
        { method: "GET", token, orgId },
      );
      return res.data as OperationalHealthCounts;
    },
  });
}
