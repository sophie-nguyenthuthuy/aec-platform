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
  DossierDetail,
  DossierStatus,
  DossierSummary,
  InvestmentType,
  PermitAlert,
  PermitDossier,
  ProjectClassification,
  StageStatus,
} from "@aec/ui/permitflow";
import { permitflowKeys } from "./keys";

export interface DossierListFilters {
  project_id?: string;
  status?: DossierStatus;
  limit?: number;
  offset?: number;
}

export interface CreateDossierRequest {
  project_id: string;
  name: string;
  classification: ProjectClassification;
  investment_type?: InvestmentType;
  location?: Record<string, unknown>;
  land_cert_file_id?: string;
  land_parcel_no?: string;
  notes?: string;
}

export interface UpdateDossierRequest {
  name?: string;
  classification?: ProjectClassification;
  investment_type?: InvestmentType;
  status?: DossierStatus;
  location?: Record<string, unknown>;
  land_parcel_no?: string;
  notes?: string;
}

export interface StageTransitionRequest {
  to_status: StageStatus;
  decision_number?: string;
  decision_date?: string;
  decision_file_id?: string;
  expiry_date?: string;
  rejection_reason?: string;
}

export function useDossiers(filters: DossierListFilters = {}) {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: permitflowKeys.dossiers(filters),
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const res = await apiFetch<DossierSummary[]>(
        "/api/v1/permitflow/dossiers",
        {
          method: "GET",
          token,
          orgId,
          query: {
            project_id: filters.project_id,
            status: filters.status,
            limit: filters.limit ?? 20,
            offset: filters.offset ?? 0,
          },
        },
      );
      return { data: (res.data ?? []) as DossierSummary[], meta: res.meta };
    },
  });
}

export function useDossier(id: string | undefined) {
  const { token, orgId } = useSession();
  return useQuery({
    enabled: Boolean(id),
    queryKey: id ? permitflowKeys.dossier(id) : ["noop"],
    queryFn: async () => {
      const res = await apiFetch<DossierDetail>(
        `/api/v1/permitflow/dossiers/${id}`,
        { method: "GET", token, orgId },
      );
      return res.data as DossierDetail;
    },
  });
}

export function useCreateDossier() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationKey: ["permitflow", "dossiers", "create"],
    mutationFn: async (payload: CreateDossierRequest) => {
      const res = await apiFetch<PermitDossier>(
        "/api/v1/permitflow/dossiers",
        { method: "POST", token, orgId, body: payload },
      );
      return res.data as PermitDossier;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: permitflowKeys.all });
    },
  });
}

export function useUpdateDossier(dossierId: string) {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationKey: ["permitflow", "dossier", dossierId, "update"],
    mutationFn: async (payload: UpdateDossierRequest) => {
      const res = await apiFetch<PermitDossier>(
        `/api/v1/permitflow/dossiers/${dossierId}`,
        { method: "PATCH", token, orgId, body: payload },
      );
      return res.data as PermitDossier;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: permitflowKeys.all });
    },
  });
}

export function useTransitionStage(dossierId: string) {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationKey: ["permitflow", "stage", "transition"],
    mutationFn: async ({
      stageId,
      payload,
    }: {
      stageId: string;
      payload: StageTransitionRequest;
    }) => {
      const res = await apiFetch(
        `/api/v1/permitflow/stages/${stageId}/transition`,
        { method: "POST", token, orgId, body: payload },
      );
      return res.data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: permitflowKeys.dossier(dossierId) });
      qc.invalidateQueries({ queryKey: permitflowKeys.all });
    },
  });
}

export function useAlerts(projectId?: string, expiringWithinDays = 60) {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: permitflowKeys.alerts({
      project_id: projectId,
      expiring_within_days: expiringWithinDays,
    }),
    queryFn: async () => {
      const res = await apiFetch<PermitAlert[]>(
        "/api/v1/permitflow/alerts",
        {
          method: "GET",
          token,
          orgId,
          query: {
            project_id: projectId,
            expiring_within_days: expiringWithinDays,
          },
        },
      );
      return (res.data ?? []) as PermitAlert[];
    },
  });
}
