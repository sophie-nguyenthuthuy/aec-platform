"use client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { ProposalGenerateRequest, ProposalGenerateResponse } from "@aec/types/winwork";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";
import { winworkKeys } from "./keys";

export function useGenerateProposal() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: ProposalGenerateRequest) => {
      const res = await apiFetch<ProposalGenerateResponse>("/api/v1/winwork/proposals/generate", {
        method: "POST",
        token,
        orgId,
        body: payload,
      });
      return res.data as ProposalGenerateResponse;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: winworkKeys.proposals() });
    },
  });
}
