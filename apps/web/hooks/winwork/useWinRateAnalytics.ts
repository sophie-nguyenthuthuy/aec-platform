"use client";
import { useQuery } from "@tanstack/react-query";
import type { WinRateAnalytics } from "@aec/types/winwork";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";
import { winworkKeys } from "./keys";

export function useWinRateAnalytics() {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: winworkKeys.analytics(),
    queryFn: async () => {
      const res = await apiFetch<WinRateAnalytics>("/api/v1/winwork/analytics/win-rate", {
        method: "GET",
        token,
        orgId,
      });
      return res.data as WinRateAnalytics;
    },
  });
}
