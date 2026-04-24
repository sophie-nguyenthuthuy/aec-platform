"use client";

import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";
import type { WarrantyItem, WarrantyStatus } from "@aec/ui/handover";
import { handoverKeys } from "./keys";

export interface WarrantyListFilters {
  project_id?: string;
  package_id?: string;
  status?: WarrantyStatus;
  expiring_within_days?: number;
  limit?: number;
  offset?: number;
}

export interface CreateWarrantyRequest {
  project_id: string;
  package_id?: string;
  item_name: string;
  category?: string;
  vendor?: string;
  contract_file_id?: string;
  warranty_period_months?: number;
  start_date?: string;
  expiry_date?: string;
  coverage?: string;
  claim_contact?: Record<string, unknown>;
  notes?: string;
}

export interface UpdateWarrantyRequest {
  status?: WarrantyStatus;
  notes?: string;
  claim_contact?: Record<string, unknown>;
}

export interface ExtractWarrantyRequest {
  project_id: string;
  package_id?: string;
  contract_file_ids: string[];
}

export interface ExtractWarrantyResponse {
  contract_file_ids: string[];
  extracted_count: number;
  items: WarrantyItem[];
}

export function useWarranties(filters: WarrantyListFilters = {}) {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: handoverKeys.warranties(filters),
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const res = await apiFetch<WarrantyItem[]>(
        "/api/v1/handover/warranties",
        {
          method: "GET",
          token,
          orgId,
          query: {
            project_id: filters.project_id,
            package_id: filters.package_id,
            status: filters.status,
            expiring_within_days: filters.expiring_within_days,
            limit: filters.limit ?? 50,
            offset: filters.offset ?? 0,
          },
        },
      );
      return { data: (res.data ?? []) as WarrantyItem[], meta: res.meta };
    },
  });
}

export function useCreateWarranty() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationKey: ["handover", "warranties", "create"],
    mutationFn: async (payload: CreateWarrantyRequest) => {
      const res = await apiFetch<WarrantyItem>("/api/v1/handover/warranties", {
        method: "POST",
        token,
        orgId,
        body: payload,
      });
      return res.data as WarrantyItem;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["handover", "warranties"] });
    },
  });
}

export function useUpdateWarranty() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationKey: ["handover", "warranties", "update"],
    mutationFn: async (args: {
      id: string;
      patch: UpdateWarrantyRequest;
    }) => {
      const res = await apiFetch<WarrantyItem>(
        `/api/v1/handover/warranties/${args.id}`,
        { method: "PATCH", token, orgId, body: args.patch },
      );
      return res.data as WarrantyItem;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["handover", "warranties"] });
    },
  });
}

export function useExtractWarranty() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationKey: ["handover", "warranties", "extract"],
    mutationFn: async (payload: ExtractWarrantyRequest) => {
      const res = await apiFetch<ExtractWarrantyResponse>(
        "/api/v1/handover/warranties/extract",
        { method: "POST", token, orgId, body: payload },
      );
      return res.data as ExtractWarrantyResponse;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["handover", "warranties"] });
    },
  });
}
