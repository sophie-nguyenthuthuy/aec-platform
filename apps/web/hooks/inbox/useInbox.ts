"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";
import type { InboxResponse } from "@aec/types/inbox";

export interface InboxFilters {
  project_id?: string;
  limit_per_source?: number;
}

export function useInbox(filters: InboxFilters = {}) {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: ["me", "inbox", filters] as const,
    placeholderData: keepPreviousData,
    // Modest staleTime — the inbox is a triage view; users will re-open
    // it across the day and a single round-trip on focus is fine.
    staleTime: 15_000,
    queryFn: async () => {
      const res = await apiFetch<InboxResponse>("/api/v1/me/inbox", {
        method: "GET",
        token,
        orgId,
        query: {
          project_id: filters.project_id,
          limit_per_source: filters.limit_per_source ?? 20,
        },
      });
      return res.data as InboxResponse;
    },
  });
}

export type { InboxResponse } from "@aec/types/inbox";
