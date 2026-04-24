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
  HandoverPackage,
  PackageDetail,
  PackageStatus,
  PackageSummary,
} from "@aec/ui/handover";
import { handoverKeys } from "./keys";

export interface PackageListFilters {
  project_id?: string;
  status?: PackageStatus;
  limit?: number;
  offset?: number;
}

export interface CreatePackageRequest {
  project_id: string;
  name: string;
  scope_summary?: Record<string, unknown>;
  auto_populate?: boolean;
}

export interface UpdatePackageRequest {
  name?: string;
  status?: PackageStatus;
  scope_summary?: Record<string, unknown>;
}

export function usePackages(filters: PackageListFilters = {}) {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: handoverKeys.packages(filters),
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const res = await apiFetch<PackageSummary[]>(
        "/api/v1/handover/packages",
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
      return { data: (res.data ?? []) as PackageSummary[], meta: res.meta };
    },
  });
}

export function usePackage(id: string | undefined) {
  const { token, orgId } = useSession();
  return useQuery({
    enabled: Boolean(id),
    queryKey: id ? handoverKeys.package(id) : ["noop"],
    queryFn: async () => {
      const res = await apiFetch<PackageDetail>(
        `/api/v1/handover/packages/${id}`,
        { method: "GET", token, orgId },
      );
      return res.data as PackageDetail;
    },
  });
}

export function useCreatePackage() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationKey: ["handover", "packages", "create"],
    mutationFn: async (payload: CreatePackageRequest) => {
      const res = await apiFetch<HandoverPackage>(
        "/api/v1/handover/packages",
        { method: "POST", token, orgId, body: payload },
      );
      return res.data as HandoverPackage;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: handoverKeys.all });
    },
  });
}

export function useUpdatePackage(packageId: string) {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationKey: ["handover", "packages", packageId, "update"],
    mutationFn: async (payload: UpdatePackageRequest) => {
      const res = await apiFetch<HandoverPackage>(
        `/api/v1/handover/packages/${packageId}`,
        { method: "PATCH", token, orgId, body: payload },
      );
      return res.data as HandoverPackage;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: handoverKeys.package(packageId) });
      qc.invalidateQueries({ queryKey: ["handover", "packages"] });
    },
  });
}
