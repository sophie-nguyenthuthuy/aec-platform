"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";
import type { ISODate, UUID } from "@aec/types/envelope";

export interface WatchedProject {
  watch_id: UUID;
  project_id: UUID;
  project_name: string;
  created_at: ISODate;
}

const watchKeys = {
  all: ["notifications", "watches"] as const,
};

export function useMyWatches() {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: watchKeys.all,
    queryFn: async () => {
      const res = await apiFetch<WatchedProject[]>(
        "/api/v1/notifications/watches",
        { method: "GET", token, orgId },
      );
      return (res.data ?? []) as WatchedProject[];
    },
  });
}

/** Convenience: is the calling user already watching this project? */
export function useIsWatching(projectId: UUID | undefined): boolean {
  const { data } = useMyWatches();
  if (!projectId || !data) return false;
  return data.some((w) => w.project_id === projectId);
}

export function useToggleWatch(projectId: UUID) {
  const { token, orgId } = useSession();
  const qc = useQueryClient();

  const watch = useMutation({
    mutationFn: async () => {
      const res = await apiFetch<{ id: UUID }>(
        "/api/v1/notifications/watches",
        {
          method: "POST",
          token,
          orgId,
          body: { project_id: projectId },
        },
      );
      return res.data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: watchKeys.all }),
  });

  const unwatch = useMutation({
    mutationFn: async () => {
      await apiFetch<null>(
        `/api/v1/notifications/watches/${projectId}`,
        { method: "DELETE", token, orgId },
      );
      return null;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: watchKeys.all }),
  });

  return { watch, unwatch };
}
