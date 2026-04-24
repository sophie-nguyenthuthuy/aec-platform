"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { Proposal } from "@aec/types/winwork";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";
import { winworkKeys } from "./keys";

export function useProposal(id: string | undefined) {
  const { token, orgId } = useSession();
  return useQuery({
    enabled: Boolean(id),
    queryKey: id ? winworkKeys.proposalDetail(id) : ["noop"],
    queryFn: async () => {
      const res = await apiFetch<Proposal>(`/api/v1/winwork/proposals/${id}`, {
        method: "GET",
        token,
        orgId,
      });
      return res.data as Proposal;
    },
  });
}

export function useUpdateProposal(id: string) {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (patch: Partial<Proposal>) => {
      const res = await apiFetch<Proposal>(`/api/v1/winwork/proposals/${id}`, {
        method: "PATCH",
        token,
        orgId,
        body: patch,
      });
      return res.data as Proposal;
    },
    onSuccess: (data) => {
      qc.setQueryData(winworkKeys.proposalDetail(id), data);
      qc.invalidateQueries({ queryKey: winworkKeys.proposals() });
    },
  });
}

export function useSendProposal(id: string) {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: { subject?: string; message?: string; cc?: string[] }) => {
      const res = await apiFetch<Proposal>(`/api/v1/winwork/proposals/${id}/send`, {
        method: "POST",
        token,
        orgId,
        body: payload,
      });
      return res.data as Proposal;
    },
    onSuccess: (data) => {
      qc.setQueryData(winworkKeys.proposalDetail(id), data);
      qc.invalidateQueries({ queryKey: winworkKeys.proposals() });
    },
  });
}

export function useMarkOutcome(id: string) {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: { status: "won" | "lost"; reason?: string; actual_fee_vnd?: number }) => {
      const res = await apiFetch<Proposal>(`/api/v1/winwork/proposals/${id}/outcome`, {
        method: "PATCH",
        token,
        orgId,
        body: payload,
      });
      return res.data as Proposal;
    },
    onSuccess: (data) => {
      qc.setQueryData(winworkKeys.proposalDetail(id), data);
      qc.invalidateQueries({ queryKey: winworkKeys.proposals() });
      qc.invalidateQueries({ queryKey: winworkKeys.analytics() });
    },
  });
}
