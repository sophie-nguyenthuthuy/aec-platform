"use client";
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import type { UUID } from "@aec/types/envelope";
import type { ProjectDashboard } from "@aec/types/pulse";
import { apiFetch } from "../../lib/api";
import { useSession } from "../../lib/auth-context";
import { pulseKeys } from "./keys";

export function useProjectDashboard(
  projectId: UUID,
): UseQueryResult<ProjectDashboard> {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: pulseKeys.dashboard(projectId),
    queryFn: async () => {
      const res = await apiFetch<ProjectDashboard>(
        `/api/v1/pulse/projects/${projectId}/dashboard`,
        { token, orgId },
      );
      if (!res.data) throw new Error("No dashboard data");
      return res.data;
    },
    refetchInterval: 60_000,
  });
}
