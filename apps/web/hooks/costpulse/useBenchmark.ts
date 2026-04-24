"use client";
import { useQuery } from "@tanstack/react-query";
import type { CostBenchmarkBucket } from "@aec/types";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";

import { costpulseKeys } from "./useEstimates";

export interface BenchmarkFilters {
  project_type?: string;
  province?: string;
}

export function useCostBenchmark(filters: BenchmarkFilters = {}) {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: [...costpulseKeys.benchmark(), filters] as const,
    queryFn: async () => {
      const res = await apiFetch<{ buckets: CostBenchmarkBucket[] }>(
        "/api/v1/costpulse/analytics/cost-benchmark",
        {
          token,
          orgId,
          query: {
            project_type: filters.project_type ?? null,
            province: filters.province ?? null,
          },
        },
      );
      return res.data?.buckets ?? [];
    },
  });
}
