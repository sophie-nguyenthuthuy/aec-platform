"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";
import type { ActivityEvent, ActivityFilters } from "@aec/types/activity";

import { activityKeys } from "./keys";

/** Fetch the cross-module activity feed. The result keeps previous data
 *  while a new query is loading so toggling filters doesn't flash empty. */
export function useActivityFeed(filters: ActivityFilters = {}) {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: activityKeys.feed(filters),
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const res = await apiFetch<ActivityEvent[]>("/api/v1/activity", {
        method: "GET",
        token,
        orgId,
        query: {
          project_id: filters.project_id,
          module: filters.module,
          since_days: filters.since_days ?? 30,
          limit: filters.limit ?? 50,
          offset: filters.offset ?? 0,
        },
      });
      return {
        data: (res.data ?? []) as ActivityEvent[],
        meta: res.meta,
      };
    },
  });
}
