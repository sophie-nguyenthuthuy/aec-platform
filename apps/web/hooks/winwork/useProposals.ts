"use client";
import { useQuery } from "@tanstack/react-query";
import type { Proposal, ProposalStatus } from "@aec/types/winwork";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";
import { winworkKeys } from "./keys";

export interface UseProposalsParams {
  page?: number;
  per_page?: number;
  status?: ProposalStatus;
  q?: string;
}

export function useProposals(params: UseProposalsParams = {}) {
  const { token, orgId } = useSession();
  const query = { page: 1, per_page: 20, ...params };
  return useQuery({
    queryKey: winworkKeys.proposalList(query),
    queryFn: async () => {
      const res = await apiFetch<Proposal[]>("/api/v1/winwork/proposals", {
        method: "GET",
        token,
        orgId,
        query,
      });
      return { items: res.data ?? [], total: res.meta?.total ?? 0 };
    },
  });
}
