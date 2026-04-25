"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";
import type {
  ProjectDetail,
  ProjectStatus,
  ProjectSummary,
  ProjectType,
} from "@aec/types/projects";

import { projectKeys } from "./keys";

export interface ProjectListFilters {
  status?: ProjectStatus | string;
  type?: ProjectType | string;
  q?: string;
  page?: number;
  per_page?: number;
}

export function useProjects(filters: ProjectListFilters = {}) {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: projectKeys.list(filters),
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const res = await apiFetch<ProjectSummary[]>("/api/v1/projects", {
        method: "GET",
        token,
        orgId,
        query: {
          status: filters.status,
          type: filters.type,
          q: filters.q,
          page: filters.page ?? 1,
          per_page: filters.per_page ?? 20,
        },
      });
      return {
        data: (res.data ?? []) as ProjectSummary[],
        meta: res.meta,
      };
    },
  });
}

export function useProject(id: string | undefined) {
  const { token, orgId } = useSession();
  return useQuery({
    enabled: Boolean(id),
    queryKey: id ? projectKeys.detail(id) : ["projects", "detail", "noop"],
    queryFn: async () => {
      const res = await apiFetch<ProjectDetail>(`/api/v1/projects/${id}`, {
        method: "GET",
        token,
        orgId,
      });
      return res.data as ProjectDetail;
    },
  });
}
