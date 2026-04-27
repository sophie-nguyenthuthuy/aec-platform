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
  Approval,
  Candidate,
  ChangeOrder,
  ChangeOrderDetail,
  CoStatus,
  LineItem,
} from "@aec/types/changeorder";

import { changeOrderKeys } from "./keys";

export interface ChangeOrderListFilters {
  project_id?: string;
  status?: CoStatus;
  limit?: number;
  offset?: number;
}

export interface CreateCoRequest {
  project_id: string;
  title: string;
  description?: string;
  number?: string;
  initiator?: string;
  cost_impact_vnd?: number;
  schedule_impact_days?: number;
}

export interface UpdateCoRequest {
  title?: string;
  description?: string;
  status?: CoStatus;
  cost_impact_vnd?: number;
  schedule_impact_days?: number;
}

export interface AddLineItemRequest {
  description: string;
  line_kind?: "add" | "delete" | "substitute";
  spec_section?: string;
  quantity?: number;
  unit?: string;
  unit_cost_vnd?: number;
  cost_vnd?: number;
  schedule_impact_days?: number;
  schedule_activity_id?: string;
  sort_order?: number;
  notes?: string;
}

export interface RecordApprovalRequest {
  to_status: CoStatus;
  notes?: string;
}

export interface ExtractRequest {
  project_id: string;
  rfi_id?: string;
  text?: string;
  source_kind?: "rfi" | "email" | "manual_paste";
}

export function useChangeOrders(filters: ChangeOrderListFilters = {}) {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: changeOrderKeys.list(filters),
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const res = await apiFetch<ChangeOrder[]>("/api/v1/changeorder/cos", {
        method: "GET",
        token,
        orgId,
        query: {
          project_id: filters.project_id,
          status: filters.status,
          limit: filters.limit ?? 20,
          offset: filters.offset ?? 0,
        },
      });
      return { data: (res.data ?? []) as ChangeOrder[], meta: res.meta };
    },
  });
}

export function useChangeOrder(id: string | undefined) {
  const { token, orgId } = useSession();
  return useQuery({
    enabled: Boolean(id),
    queryKey: id ? changeOrderKeys.detail(id) : ["changeorder", "noop"],
    queryFn: async () => {
      const res = await apiFetch<ChangeOrderDetail>(
        `/api/v1/changeorder/cos/${id}`,
        { method: "GET", token, orgId },
      );
      return res.data as ChangeOrderDetail;
    },
  });
}

export function useCreateChangeOrder() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: CreateCoRequest) => {
      const res = await apiFetch<ChangeOrder>("/api/v1/changeorder/cos", {
        method: "POST",
        token,
        orgId,
        body: payload,
      });
      return res.data as ChangeOrder;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: changeOrderKeys.all }),
  });
}

export interface PriceSuggestion {
  material_price_id: string;
  material_code: string;
  name: string;
  category: string | null;
  unit: string;
  price_vnd: number;
  province: string | null;
  source: string | null;
  effective_date: string | null;
}

export interface PriceSuggestionsResponse {
  query: string | null;
  spec_section: string | null;
  results: PriceSuggestion[];
}

/** CostPulse-backed unit price hints for a CO line-item form. */
export function usePriceSuggestions(opts: {
  q?: string;
  spec_section?: string;
  province?: string;
  limit?: number;
  enabled?: boolean;
}) {
  const { token, orgId } = useSession();
  const enabled =
    (opts.enabled ?? true) && Boolean(opts.q?.trim() || opts.spec_section?.trim());
  return useQuery({
    enabled,
    // Stable key — same inputs reuse the cache entry.
    queryKey: [
      "changeorder",
      "price-suggestions",
      opts.q ?? "",
      opts.spec_section ?? "",
      opts.province ?? "",
      opts.limit ?? 5,
    ] as const,
    staleTime: 30_000, // hints don't change often; avoid hammering the API
    queryFn: async () => {
      const res = await apiFetch<PriceSuggestionsResponse>(
        "/api/v1/changeorder/price-suggestions",
        {
          method: "GET",
          token,
          orgId,
          query: {
            q: opts.q,
            spec_section: opts.spec_section,
            province: opts.province,
            limit: opts.limit ?? 5,
          },
        },
      );
      return (
        (res.data ?? {
          query: opts.q ?? null,
          spec_section: opts.spec_section ?? null,
          results: [],
        }) as PriceSuggestionsResponse
      );
    },
  });
}

export function useAddLineItem(coId: string) {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: AddLineItemRequest) => {
      const res = await apiFetch<LineItem>(
        `/api/v1/changeorder/cos/${coId}/line-items`,
        { method: "POST", token, orgId, body: payload },
      );
      return res.data as LineItem;
    },
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: changeOrderKeys.detail(coId) }),
  });
}

export function useRecordApproval(coId: string) {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: RecordApprovalRequest) => {
      const res = await apiFetch<Approval>(
        `/api/v1/changeorder/cos/${coId}/approvals`,
        { method: "POST", token, orgId, body: payload },
      );
      return res.data as Approval;
    },
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: changeOrderKeys.detail(coId) }),
  });
}

export function useExtractCandidates() {
  const { token, orgId } = useSession();
  return useMutation({
    mutationFn: async (payload: ExtractRequest) => {
      const res = await apiFetch<Candidate[]>("/api/v1/changeorder/extract", {
        method: "POST",
        token,
        orgId,
        body: payload,
      });
      return (res.data ?? []) as Candidate[];
    },
  });
}

export function useAcceptCandidate() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({
      candidateId,
      titleOverride,
      descriptionOverride,
    }: {
      candidateId: string;
      titleOverride?: string;
      descriptionOverride?: string;
    }) => {
      const res = await apiFetch<ChangeOrder>(
        `/api/v1/changeorder/candidates/${candidateId}/accept`,
        {
          method: "POST",
          token,
          orgId,
          body: {
            title_override: titleOverride,
            description_override: descriptionOverride,
          },
        },
      );
      return res.data as ChangeOrder;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: changeOrderKeys.all }),
  });
}

export function useAnalyzeImpact(coId: string) {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation<Record<string, unknown>, Error, boolean | undefined>({
    mutationFn: async (force) => {
      const res = await apiFetch<Record<string, unknown>>(
        `/api/v1/changeorder/cos/${coId}/analyze`,
        { method: "POST", token, orgId, body: { force: force ?? false } },
      );
      return res.data as Record<string, unknown>;
    },
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: changeOrderKeys.detail(coId) }),
  });
}

export type { ChangeOrder, ChangeOrderDetail, Candidate, LineItem, Approval };
