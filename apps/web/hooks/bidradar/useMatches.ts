"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";
import type {
  CreateProposalResponse,
  MatchStatus,
  TenderMatch,
  TenderMatchWithTender,
} from "@aec/ui/bidradar";
import { bidradarKeys } from "./keys";

export interface MatchFilters {
  status?: MatchStatus;
  min_score?: number;
  recommended_only?: boolean;
  limit?: number;
  offset?: number;
}

export function useMatches(filters: MatchFilters = {}) {
  const { token, orgId } = useSession();
  const query = {
    status: filters.status,
    min_score: filters.min_score,
    recommended_only: filters.recommended_only,
    limit: filters.limit ?? 20,
    offset: filters.offset ?? 0,
  };
  return useQuery({
    queryKey: bidradarKeys.matches(query),
    queryFn: async () => {
      const res = await apiFetch<TenderMatchWithTender[]>("/api/v1/bidradar/matches", {
        method: "GET",
        query,
        token,
        orgId,
      });
      return {
        items: res.data ?? [],
        total: res.meta?.total ?? 0,
      };
    },
  });
}

export function useMatch(matchId: string | null) {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: bidradarKeys.match(matchId ?? ""),
    enabled: Boolean(matchId),
    queryFn: async () => {
      const res = await apiFetch<TenderMatchWithTender>(
        `/api/v1/bidradar/matches/${matchId}`,
        { method: "GET", token, orgId },
      );
      return res.data!;
    },
  });
}

export function useUpdateMatchStatus() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (args: { matchId: string; status: MatchStatus }) => {
      const res = await apiFetch<TenderMatch>(
        `/api/v1/bidradar/matches/${args.matchId}/status`,
        { method: "PATCH", body: { status: args.status }, token, orgId },
      );
      return res.data!;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: bidradarKeys.all });
    },
  });
}

export function useCreateProposal() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (matchId: string) => {
      const res = await apiFetch<CreateProposalResponse>(
        `/api/v1/bidradar/matches/${matchId}/create-proposal`,
        { method: "POST", token, orgId },
      );
      return res.data!;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: bidradarKeys.all });
    },
  });
}
