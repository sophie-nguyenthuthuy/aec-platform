"use client";

import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";
import type {
  ClaimStatus,
  ClaimSummary,
  CumulativeView,
  PartyDecision,
  PaymentClaim,
  PaymentClaimDetail,
} from "@aec/ui/thanhtoan";
import { thanhtoanKeys } from "./keys";

export interface ClaimListFilters {
  project_id?: string;
  status?: ClaimStatus;
  period_year?: number;
  limit?: number;
  offset?: number;
}

export interface CreateClaimRequest {
  project_id: string;
  claim_no: string;
  period_start: string;
  period_end: string;
  vat_pct?: string;
  retention_pct?: string;
  tndn_pct?: string;
  due_at?: string;
  notes?: string;
}

export interface SignClaimRequest {
  role: "cdt" | "tvgs";
  decision: PartyDecision;
  comment?: string;
}

export interface MarkPaidRequest {
  paid_at: string;
  payment_reference?: string;
}

export function useClaims(filters: ClaimListFilters = {}) {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: thanhtoanKeys.claims(filters),
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const res = await apiFetch<ClaimSummary[]>(
        "/api/v1/thanhtoan/claims",
        {
          method: "GET",
          token,
          orgId,
          query: {
            project_id: filters.project_id,
            status: filters.status,
            period_year: filters.period_year,
            limit: filters.limit ?? 20,
            offset: filters.offset ?? 0,
          },
        },
      );
      return { data: (res.data ?? []) as ClaimSummary[], meta: res.meta };
    },
  });
}

export function useClaim(id: string | undefined) {
  const { token, orgId } = useSession();
  return useQuery({
    enabled: Boolean(id),
    queryKey: id ? thanhtoanKeys.claim(id) : ["noop"],
    queryFn: async () => {
      const res = await apiFetch<PaymentClaimDetail>(
        `/api/v1/thanhtoan/claims/${id}`,
        { method: "GET", token, orgId },
      );
      return res.data as PaymentClaimDetail;
    },
  });
}

export function useCumulative(id: string | undefined) {
  const { token, orgId } = useSession();
  return useQuery({
    enabled: Boolean(id),
    queryKey: id ? thanhtoanKeys.cumulative(id) : ["noop"],
    queryFn: async () => {
      const res = await apiFetch<CumulativeView>(
        `/api/v1/thanhtoan/claims/${id}/cumulative`,
        { method: "GET", token, orgId },
      );
      return res.data as CumulativeView;
    },
  });
}

export function useCreateClaim() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationKey: ["thanhtoan", "claims", "create"],
    mutationFn: async (payload: CreateClaimRequest) => {
      const res = await apiFetch<PaymentClaim>(
        "/api/v1/thanhtoan/claims",
        { method: "POST", token, orgId, body: payload },
      );
      return res.data as PaymentClaim;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: thanhtoanKeys.all });
    },
  });
}

export function useSubmitClaim(claimId: string) {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationKey: ["thanhtoan", "claim", claimId, "submit"],
    mutationFn: async (notes?: string) => {
      const res = await apiFetch<PaymentClaim>(
        `/api/v1/thanhtoan/claims/${claimId}/submit`,
        { method: "POST", token, orgId, body: { notes } },
      );
      return res.data as PaymentClaim;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: thanhtoanKeys.claim(claimId) });
      qc.invalidateQueries({ queryKey: thanhtoanKeys.all });
    },
  });
}

export function useSignClaim(claimId: string) {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationKey: ["thanhtoan", "claim", claimId, "sign"],
    mutationFn: async (payload: SignClaimRequest) => {
      const res = await apiFetch<PaymentClaim>(
        `/api/v1/thanhtoan/claims/${claimId}/sign`,
        { method: "POST", token, orgId, body: payload },
      );
      return res.data as PaymentClaim;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: thanhtoanKeys.claim(claimId) });
      qc.invalidateQueries({ queryKey: thanhtoanKeys.all });
    },
  });
}

export function useMarkPaid(claimId: string) {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationKey: ["thanhtoan", "claim", claimId, "paid"],
    mutationFn: async (payload: MarkPaidRequest) => {
      const res = await apiFetch<PaymentClaim>(
        `/api/v1/thanhtoan/claims/${claimId}/mark-paid`,
        { method: "POST", token, orgId, body: payload },
      );
      return res.data as PaymentClaim;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: thanhtoanKeys.claim(claimId) });
      qc.invalidateQueries({ queryKey: thanhtoanKeys.all });
    },
  });
}
