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
  CertDetail,
  CertStatus,
  CertSummary,
  CertSystem,
  GapToNextLevel,
  GreenCertification,
  ScoreResult,
  TargetLevel,
} from "@aec/ui/greenmark";
import { greenmarkKeys } from "./keys";

export interface CertListFilters {
  project_id?: string;
  system?: CertSystem;
  status?: CertStatus;
  limit?: number;
  offset?: number;
}

export interface CreateCertRequest {
  project_id: string;
  system: CertSystem;
  target_level: TargetLevel;
  project_brief?: Record<string, unknown>;
  assessor_name?: string;
  notes?: string;
}

export function useCerts(filters: CertListFilters = {}) {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: greenmarkKeys.certs(filters),
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const res = await apiFetch<CertSummary[]>(
        "/api/v1/greenmark/certifications",
        {
          method: "GET",
          token,
          orgId,
          query: {
            project_id: filters.project_id,
            system: filters.system,
            status: filters.status,
            limit: filters.limit ?? 20,
            offset: filters.offset ?? 0,
          },
        },
      );
      return { data: (res.data ?? []) as CertSummary[], meta: res.meta };
    },
  });
}

export function useCert(id: string | undefined) {
  const { token, orgId } = useSession();
  return useQuery({
    enabled: Boolean(id),
    queryKey: id ? greenmarkKeys.cert(id) : ["noop"],
    queryFn: async () => {
      const res = await apiFetch<CertDetail>(
        `/api/v1/greenmark/certifications/${id}`,
        { method: "GET", token, orgId },
      );
      return res.data as CertDetail;
    },
  });
}

export function useCreateCert() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationKey: ["greenmark", "certifications", "create"],
    mutationFn: async (payload: CreateCertRequest) => {
      const res = await apiFetch<GreenCertification>(
        "/api/v1/greenmark/certifications",
        { method: "POST", token, orgId, body: payload },
      );
      return res.data as GreenCertification;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: greenmarkKeys.all });
    },
  });
}

export function useSeedCredits(certId: string) {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationKey: ["greenmark", "cert", certId, "seed-credits"],
    mutationFn: async () => {
      const res = await apiFetch(
        `/api/v1/greenmark/certifications/${certId}/seed-credits`,
        { method: "POST", token, orgId, body: { template_version: "vgbc_lotus_v3" } },
      );
      return res.data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: greenmarkKeys.cert(certId) });
    },
  });
}

export function useScoreCert(certId: string) {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationKey: ["greenmark", "cert", certId, "score"],
    mutationFn: async () => {
      const res = await apiFetch<ScoreResult>(
        `/api/v1/greenmark/certifications/${certId}/score`,
        { method: "POST", token, orgId, body: {} },
      );
      return res.data as ScoreResult;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: greenmarkKeys.cert(certId) });
      qc.invalidateQueries({ queryKey: greenmarkKeys.all });
    },
  });
}

export function useGap(certId: string | undefined) {
  const { token, orgId } = useSession();
  return useQuery({
    enabled: Boolean(certId),
    queryKey: certId ? greenmarkKeys.gap(certId) : ["noop"],
    queryFn: async () => {
      const res = await apiFetch<GapToNextLevel>(
        `/api/v1/greenmark/certifications/${certId}/gap`,
        { method: "GET", token, orgId },
      );
      return res.data as GapToNextLevel;
    },
  });
}
