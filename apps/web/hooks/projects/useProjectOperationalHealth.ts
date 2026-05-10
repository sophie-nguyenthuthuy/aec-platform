"use client";

/**
 * `GET /api/v1/projects/{id}/operational-health` (cycle V3).
 *
 * Returns four counts the project-page widget renders. Each count
 * is click-through to the corresponding module listing.
 *
 * Drives the "Project health" panel at the top of `/projects/[id]`.
 * Refetch every 60s — the underlying counts shift on user actions
 * (someone signs off a punch item, a reviewer approves a submittal)
 * but a 60s stale view is fine for "what needs my attention" UX.
 *
 * Member role is sufficient on the server side. Viewer 403s; the
 * widget hides itself in that case rather than showing an error
 * banner — viewers see other parts of the project page anyway.
 */

import { useQuery } from "@tanstack/react-query";

import { ApiError, apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";


export interface ProjectOperationalHealthCounts {
  /** Punch items past their due_date AND not yet verified. */
  overdue_punch_items: number;
  /** Submittals in submitted/resubmitted state — awaiting review. */
  pending_submittals: number;
  /** RFQs whose deadline has passed but the cron hasn't yet auto-closed. */
  expired_rfqs: number;
  /** Change orders in submitted/under_review/pending_approval. */
  pending_change_orders: number;
}


export function useProjectOperationalHealth(projectId: string | undefined) {
  const { token, orgId } = useSession();
  return useQuery({
    enabled: Boolean(projectId),
    queryKey: ["projects", "operational-health", projectId] as const,
    refetchInterval: 60_000,
    retry: (failureCount, err) => {
      // 403 = viewer caller — hide the widget rather than surface
      // an error.
      if (err instanceof ApiError && err.status === 403) return false;
      return failureCount < 3;
    },
    queryFn: async () => {
      const res = await apiFetch<ProjectOperationalHealthCounts>(
        `/api/v1/projects/${projectId}/operational-health`,
        { method: "GET", token, orgId },
      );
      return res.data as ProjectOperationalHealthCounts;
    },
  });
}
