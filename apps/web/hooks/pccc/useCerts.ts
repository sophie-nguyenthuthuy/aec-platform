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
  BuildingClass,
  CertAlert,
  CertDetail,
  CertStatus,
  CertSummary,
  CertType,
  FireCert,
  HazardCategory,
} from "@aec/ui/pccc";
import { pcccKeys } from "./keys";

export interface CertListFilters {
  project_id?: string;
  cert_type?: CertType;
  status?: CertStatus;
  expiring_within_days?: number;
  limit?: number;
  offset?: number;
}

export interface CreateCertRequest {
  project_id: string;
  cert_type: CertType;
  reference_no: string;
  hazard_category: HazardCategory;
  building_class: BuildingClass;
  pc07_unit: string;
  height_m?: number;
  floors_above?: number;
  floors_below?: number;
  area_sqm?: number;
  occupant_load?: number;
  notes?: string;
}

export function useCerts(filters: CertListFilters = {}) {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: pcccKeys.certs(filters),
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const res = await apiFetch<CertSummary[]>("/api/v1/pccc/certs", {
        method: "GET",
        token,
        orgId,
        query: {
          project_id: filters.project_id,
          cert_type: filters.cert_type,
          status: filters.status,
          expiring_within_days: filters.expiring_within_days,
          limit: filters.limit ?? 20,
          offset: filters.offset ?? 0,
        },
      });
      return { data: (res.data ?? []) as CertSummary[], meta: res.meta };
    },
  });
}

export function useCert(id: string | undefined) {
  const { token, orgId } = useSession();
  return useQuery({
    enabled: Boolean(id),
    queryKey: id ? pcccKeys.cert(id) : ["noop"],
    queryFn: async () => {
      const res = await apiFetch<CertDetail>(`/api/v1/pccc/certs/${id}`, {
        method: "GET",
        token,
        orgId,
      });
      return res.data as CertDetail;
    },
  });
}

export function useCreateCert() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationKey: ["pccc", "certs", "create"],
    mutationFn: async (payload: CreateCertRequest) => {
      const res = await apiFetch<FireCert>("/api/v1/pccc/certs", {
        method: "POST",
        token,
        orgId,
        body: payload,
      });
      return res.data as FireCert;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: pcccKeys.all });
    },
  });
}

export function useSeedChecklist(certId: string) {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationKey: ["pccc", "cert", certId, "seed-checklist"],
    mutationFn: async () => {
      const res = await apiFetch(
        `/api/v1/pccc/certs/${certId}/checklist/seed`,
        {
          method: "POST",
          token,
          orgId,
          body: { template_version: "qcvn_06_2022_v1" },
        },
      );
      return res.data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: pcccKeys.cert(certId) });
    },
  });
}

export function useAlerts(projectId?: string, expiringWithinDays = 90) {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: pcccKeys.alerts({
      project_id: projectId,
      expiring_within_days: expiringWithinDays,
    }),
    queryFn: async () => {
      const res = await apiFetch<CertAlert[]>("/api/v1/pccc/alerts", {
        method: "GET",
        token,
        orgId,
        query: {
          project_id: projectId,
          expiring_within_days: expiringWithinDays,
        },
      });
      return (res.data ?? []) as CertAlert[];
    },
  });
}
