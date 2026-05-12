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
  Bond,
  BondAlert,
  BondDetail,
  BondStatus,
  BondSummary,
  BondType,
} from "@aec/ui/bondline";
import { bondlineKeys } from "./keys";

export interface BondListFilters {
  project_id?: string;
  bond_type?: BondType;
  status?: BondStatus;
  issuing_bank?: string;
  expiring_within_days?: number;
  limit?: number;
  offset?: number;
}

export interface CreateBondRequest {
  project_id: string;
  bond_type: BondType;
  bond_no: string;
  issuing_bank: string;
  bank_branch?: string;
  beneficiary_name: string;
  beneficiary_mst?: string;
  face_amount_vnd: number;
  contract_value_vnd?: number;
  coverage_pct?: string;
  issue_date: string;
  expiry_date: string;
  contract_no?: string;
  notes?: string;
}

export interface ReleaseBondRequest {
  released_at: string;
  released_reason: string;
}

export function useBonds(filters: BondListFilters = {}) {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: bondlineKeys.bonds(filters),
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const res = await apiFetch<BondSummary[]>("/api/v1/bondline/bonds", {
        method: "GET",
        token,
        orgId,
        query: {
          project_id: filters.project_id,
          bond_type: filters.bond_type,
          status: filters.status,
          issuing_bank: filters.issuing_bank,
          expiring_within_days: filters.expiring_within_days,
          limit: filters.limit ?? 20,
          offset: filters.offset ?? 0,
        },
      });
      return { data: (res.data ?? []) as BondSummary[], meta: res.meta };
    },
  });
}

export function useBond(id: string | undefined) {
  const { token, orgId } = useSession();
  return useQuery({
    enabled: Boolean(id),
    queryKey: id ? bondlineKeys.bond(id) : ["noop"],
    queryFn: async () => {
      const res = await apiFetch<BondDetail>(`/api/v1/bondline/bonds/${id}`, {
        method: "GET",
        token,
        orgId,
      });
      return res.data as BondDetail;
    },
  });
}

export function useCreateBond() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationKey: ["bondline", "bonds", "create"],
    mutationFn: async (payload: CreateBondRequest) => {
      const res = await apiFetch<Bond>("/api/v1/bondline/bonds", {
        method: "POST",
        token,
        orgId,
        body: payload,
      });
      return res.data as Bond;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: bondlineKeys.all });
    },
  });
}

export function useReleaseBond(bondId: string) {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationKey: ["bondline", "bond", bondId, "release"],
    mutationFn: async (payload: ReleaseBondRequest) => {
      const res = await apiFetch<Bond>(
        `/api/v1/bondline/bonds/${bondId}/release`,
        { method: "POST", token, orgId, body: payload },
      );
      return res.data as Bond;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: bondlineKeys.bond(bondId) });
      qc.invalidateQueries({ queryKey: bondlineKeys.all });
    },
  });
}

export function useBondAlerts(projectId?: string, expiringWithinDays = 60) {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: bondlineKeys.alerts({
      project_id: projectId,
      expiring_within_days: expiringWithinDays,
    }),
    queryFn: async () => {
      const res = await apiFetch<BondAlert[]>("/api/v1/bondline/alerts", {
        method: "GET",
        token,
        orgId,
        query: {
          project_id: projectId,
          expiring_within_days: expiringWithinDays,
        },
      });
      return (res.data ?? []) as BondAlert[];
    },
  });
}
