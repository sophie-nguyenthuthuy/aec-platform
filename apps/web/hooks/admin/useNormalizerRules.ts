"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";

import { adminKeys } from "./useScraperRuns";

/**
 * One row from `normalizer_rules`. Mirrors `schemas.admin.NormalizerRuleOut`.
 *
 * `pattern` is a Python `re` regex (case-insensitive at runtime). The
 * server validates compilation on POST/PATCH so a 400 will surface in
 * the mutation `error` rather than landing as a silent "0-hit rule" in
 * production telemetry.
 */
export interface NormalizerRule {
  id: string;
  priority: number;
  pattern: string;
  material_code: string;
  category: string | null;
  canonical_name: string;
  preferred_units: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface NormalizerRuleCreatePayload {
  priority: number;
  pattern: string;
  material_code: string;
  category?: string | null;
  canonical_name: string;
  preferred_units?: string;
  enabled?: boolean;
}

/** PATCH-shaped: only set fields you're actually changing. */
export type NormalizerRuleUpdatePayload = Partial<NormalizerRuleCreatePayload>;

const rulesKey = [...adminKeys.all, "normalizer-rules"] as const;


export function useNormalizerRules() {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: rulesKey,
    queryFn: async () => {
      const res = await apiFetch<NormalizerRule[]>("/api/v1/admin/normalizer-rules", {
        token,
        orgId,
      });
      return res.data ?? [];
    },
  });
}


export function useCreateNormalizerRule() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: NormalizerRuleCreatePayload) => {
      const res = await apiFetch<NormalizerRule>("/api/v1/admin/normalizer-rules", {
        token,
        orgId,
        method: "POST",
        body: payload,
      });
      return res.data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: rulesKey });
    },
  });
}


export function useUpdateNormalizerRule() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, ...payload }: { id: string } & NormalizerRuleUpdatePayload) => {
      const res = await apiFetch<NormalizerRule>(`/api/v1/admin/normalizer-rules/${id}`, {
        token,
        orgId,
        method: "PATCH",
        body: payload,
      });
      return res.data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: rulesKey });
    },
  });
}


export function useDeleteNormalizerRule() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      await apiFetch<null>(`/api/v1/admin/normalizer-rules/${id}`, {
        token,
        orgId,
        method: "DELETE",
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: rulesKey });
    },
  });
}
