"use client";
import { useQuery } from "@tanstack/react-query";
import type { Discipline, FeeBenchmark } from "@aec/types/winwork";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";
import { winworkKeys } from "./keys";

export interface UseBenchmarksParams {
  discipline?: Discipline;
  project_type?: string;
  country_code?: string;
  province?: string;
}

export function useBenchmarks(params: UseBenchmarksParams = {}) {
  const { token, orgId } = useSession();
  const query = { country_code: "VN", ...params };
  return useQuery({
    queryKey: winworkKeys.benchmarks(query),
    queryFn: async () => {
      const res = await apiFetch<FeeBenchmark[]>("/api/v1/winwork/benchmarks", {
        method: "GET",
        token,
        orgId,
        query,
      });
      return res.data ?? [];
    },
  });
}
