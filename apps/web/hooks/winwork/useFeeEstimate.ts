"use client";
import { useMutation } from "@tanstack/react-query";
import type { FeeEstimateRequest, FeeEstimateResponse } from "@aec/types/winwork";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";

export function useFeeEstimate() {
  const { token, orgId } = useSession();
  return useMutation({
    mutationFn: async (payload: FeeEstimateRequest) => {
      const res = await apiFetch<FeeEstimateResponse>("/api/v1/winwork/fee-estimate", {
        method: "POST",
        token,
        orgId,
        body: payload,
      });
      return res.data as FeeEstimateResponse;
    },
  });
}
