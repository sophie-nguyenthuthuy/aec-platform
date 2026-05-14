"use client";

import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";


// ---------- Types ----------
//
// Mirrors the JSON shape returned by routers/my_work.py. Lifted here so
// the page imports a single source of truth (vs duplicating the union
// of fields inline).

export type WorkKind = "task" | "activity";
export type StatusBucket = "open" | "overdue" | "all";
export type KindFilter = WorkKind;
export type AssigneeScope = "me" | "anyone";

export interface WorkItem {
  kind: WorkKind;
  id: string;
  title: string;
  status: string;
  priority: string | null;
  project_id: string;
  project_name: string;
  assignee_id: string | null;
  assignee_email: string | null;
  due_date: string | null;
  percent_complete: number | null;
  created_at: string | null;
}

export interface WorkListPage {
  items: WorkItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface WorkSummary {
  open: number;
  overdue: number;
  due_today: number;
  completed_week: number;
}

export interface UseMyWorkFilters {
  assignee?: AssigneeScope;
  status?: StatusBucket;
  kind?: KindFilter;
  projectId?: string;
  limit?: number;
  offset?: number;
}


/**
 * Fetch the aggregated cross-module work feed. The query key includes
 * every filter param so a tab switch (open ↔ overdue) returns from the
 * cache when the user flips back, and an assignee change triggers a
 * fresh request without colliding with the previous data.
 */
export function useMyWorkList(filters: UseMyWorkFilters = {}) {
  const { token, orgId } = useSession();
  const params = new URLSearchParams();
  if (filters.assignee) params.set("assignee", filters.assignee);
  if (filters.status) params.set("status", filters.status);
  if (filters.kind) params.set("kind", filters.kind);
  if (filters.projectId) params.set("project_id", filters.projectId);
  if (filters.limit != null) params.set("limit", String(filters.limit));
  if (filters.offset != null) params.set("offset", String(filters.offset));

  const queryString = params.toString();
  const path = queryString ? `/api/v1/my-work?${queryString}` : "/api/v1/my-work";

  return useQuery({
    queryKey: ["my-work", "list", filters, orgId],
    queryFn: async () => {
      const res = await apiFetch<WorkListPage>(path, { token, orgId });
      return res.data as WorkListPage;
    },
    enabled: Boolean(token && orgId),
  });
}


/**
 * Fetch the KPI tile summary. Separate hook + query key so the tiles
 * can refetch on a faster cadence than the row list, and so the list
 * doesn't have to re-run the FILTER aggregates on every pagination.
 */
export function useMyWorkSummary(assignee: AssigneeScope = "anyone") {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: ["my-work", "summary", assignee, orgId],
    queryFn: async () => {
      const res = await apiFetch<WorkSummary>(
        `/api/v1/my-work/summary?assignee=${assignee}`,
        { token, orgId },
      );
      return res.data as WorkSummary;
    },
    enabled: Boolean(token && orgId),
    // Recompute summaries every 60s so a teammate's status change lights
    // up the badge without a manual refresh. The list query is on-demand.
    refetchInterval: 60_000,
  });
}
