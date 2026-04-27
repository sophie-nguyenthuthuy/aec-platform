"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type {
  AiEstimateResult,
  EstimateDetail,
  EstimateFromBriefInput,
  EstimateFromDrawingsInput,
  EstimateStatus,
  EstimateSummary,
  UUID,
} from "@aec/types";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";

export const costpulseKeys = {
  all: ["costpulse"] as const,
  estimates: () => [...costpulseKeys.all, "estimates"] as const,
  estimatesList: (filters: EstimateListFilters) =>
    [...costpulseKeys.estimates(), "list", filters] as const,
  estimateDetail: (id: UUID) => [...costpulseKeys.estimates(), "detail", id] as const,
  prices: () => [...costpulseKeys.all, "prices"] as const,
  priceHistory: (code: string, province?: string | null) =>
    [...costpulseKeys.prices(), "history", code, province ?? null] as const,
  suppliers: () => [...costpulseKeys.all, "suppliers"] as const,
  rfq: () => [...costpulseKeys.all, "rfq"] as const,
  benchmark: () => [...costpulseKeys.all, "benchmark"] as const,
};

export interface EstimateListFilters {
  project_id?: UUID;
  status?: EstimateStatus;
  page?: number;
  per_page?: number;
}

export function useEstimates(filters: EstimateListFilters = {}) {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: costpulseKeys.estimatesList(filters),
    queryFn: async () => {
      const res = await apiFetch<EstimateSummary[]>("/api/v1/costpulse/estimates", {
        token,
        orgId,
        query: {
          project_id: filters.project_id ?? null,
          status: filters.status ?? null,
          page: filters.page ?? 1,
          per_page: filters.per_page ?? 20,
        },
      });
      return { items: res.data ?? [], meta: res.meta };
    },
  });
}

export function useEstimate(id: UUID | null) {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: costpulseKeys.estimateDetail(id ?? ("" as UUID)),
    enabled: Boolean(id),
    queryFn: async () => {
      const res = await apiFetch<EstimateDetail>(`/api/v1/costpulse/estimates/${id}`, {
        token,
        orgId,
      });
      if (!res.data) throw new Error("Estimate not found");
      return res.data;
    },
  });
}

export function useEstimateFromBrief() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (input: EstimateFromBriefInput) => {
      const res = await apiFetch<AiEstimateResult>("/api/v1/costpulse/estimate/from-brief", {
        method: "POST",
        body: input,
        token,
        orgId,
      });
      if (!res.data) throw new Error("Empty response");
      return res.data;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: costpulseKeys.estimates() });
    },
  });
}

export function useEstimateFromDrawings() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (input: EstimateFromDrawingsInput) => {
      const res = await apiFetch<AiEstimateResult>("/api/v1/costpulse/estimate/from-drawings", {
        method: "POST",
        body: input,
        token,
        orgId,
      });
      if (!res.data) throw new Error("Empty response");
      return res.data;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: costpulseKeys.estimates() });
    },
  });
}

export function useUpdateBoq(estimateId: UUID) {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (items: EstimateDetail["items"]) => {
      const res = await apiFetch<EstimateDetail>(
        `/api/v1/costpulse/estimates/${estimateId}/boq`,
        {
          method: "PUT",
          body: { items, recompute_totals: true },
          token,
          orgId,
        },
      );
      if (!res.data) throw new Error("Empty response");
      return res.data;
    },
    onSuccess: (data) => {
      qc.setQueryData(costpulseKeys.estimateDetail(estimateId), data);
      void qc.invalidateQueries({ queryKey: costpulseKeys.estimates() });
    },
  });
}


/**
 * Upload an .xlsx file to replace this estimate's BOQ.
 *
 * Bypasses `apiFetch` because that helper hardcodes
 * `Content-Type: application/json`; multipart uploads need the browser
 * to set the boundary header itself. We still pass token + X-Org-ID
 * by hand so the auth contract matches.
 */
export function useImportBoq(estimateId: UUID) {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (file: File) => {
      const fd = new FormData();
      fd.append("file", file);
      const baseUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
      const res = await fetch(
        `${baseUrl}/api/v1/costpulse/estimates/${estimateId}/boq/import`,
        {
          method: "POST",
          body: fd,
          headers: {
            Authorization: `Bearer ${token}`,
            "X-Org-ID": orgId,
            // Note: do NOT set Content-Type — fetch needs to add the
            // multipart boundary on its own.
          },
        },
      );
      const json = (await res.json().catch(() => ({}))) as {
        data?: EstimateDetail;
        errors?: Array<{ message: string }>;
      };
      if (!res.ok) {
        throw new Error(json.errors?.[0]?.message ?? `HTTP ${res.status}`);
      }
      if (!json.data) throw new Error("Empty response from import");
      return json.data;
    },
    onSuccess: (data) => {
      qc.setQueryData(costpulseKeys.estimateDetail(estimateId), data);
      void qc.invalidateQueries({ queryKey: costpulseKeys.estimates() });
    },
  });
}


/**
 * Trigger a browser download of the BOQ as Excel or PDF.
 *
 * Returns a callable that fetches the binary blob (with Bearer auth)
 * and synthesises a download via a temporary `<a download>` element.
 * We don't open the URL directly because the auth header doesn't
 * survive a top-level navigation — the bearer token would be missing
 * on the server side.
 */
export function useExportBoq(estimateId: UUID) {
  const { token, orgId } = useSession();
  return async function downloadBoq(format: "xlsx" | "pdf"): Promise<void> {
    const baseUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
    const res = await fetch(
      `${baseUrl}/api/v1/costpulse/estimates/${estimateId}/boq/export.${format}`,
      {
        headers: {
          Authorization: `Bearer ${token}`,
          "X-Org-ID": orgId,
        },
      },
    );
    if (!res.ok) {
      throw new Error(`Export failed: HTTP ${res.status}`);
    }
    const filename = parseFilenameFromContentDisposition(
      res.headers.get("Content-Disposition"),
      `boq.${format}`,
    );
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    try {
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
    } finally {
      // Revoke after a tick so the browser has time to start the download.
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
  };
}


function parseFilenameFromContentDisposition(
  header: string | null,
  fallback: string,
): string {
  if (!header) return fallback;
  // Tolerant match: `attachment; filename="foo.xlsx"` or unquoted.
  const match = header.match(/filename\*?=(?:"([^"]+)"|([^;]+))/i);
  if (!match) return fallback;
  // One of the two capture groups will be set, never both.
  const captured = match[1] ?? match[2];
  return captured ? captured.trim() : fallback;
}

export function useApproveEstimate(estimateId: UUID) {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const res = await apiFetch<EstimateSummary>(
        `/api/v1/costpulse/estimates/${estimateId}/approve`,
        { method: "POST", token, orgId },
      );
      return res.data;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: costpulseKeys.estimates() });
      void qc.invalidateQueries({ queryKey: costpulseKeys.estimateDetail(estimateId) });
    },
  });
}
