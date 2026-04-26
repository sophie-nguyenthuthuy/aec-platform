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
  DailyLogDetail,
  DailyLogStatus,
  DailyLogSummary,
  EquipmentEntry,
  ManpowerEntry,
  Observation,
  PatternsResponse,
} from "@aec/types/dailylog";

import { dailylogKeys } from "./keys";

export interface DailyLogListFilters {
  project_id?: string;
  status?: DailyLogStatus;
  date_from?: string;
  date_to?: string;
  limit?: number;
  offset?: number;
}

export interface CreateDailyLogRequest {
  project_id: string;
  log_date: string;
  weather?: Record<string, unknown>;
  narrative?: string;
  work_completed?: string;
  issues_observed?: string;
  manpower?: ManpowerEntry[];
  equipment?: EquipmentEntry[];
  auto_extract?: boolean;
}

export interface UpdateDailyLogRequest {
  weather?: Record<string, unknown>;
  narrative?: string;
  work_completed?: string;
  issues_observed?: string;
  status?: DailyLogStatus;
  manpower?: ManpowerEntry[];
  equipment?: EquipmentEntry[];
}

export function useDailyLogs(filters: DailyLogListFilters = {}) {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: dailylogKeys.list(filters),
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const res = await apiFetch<DailyLogSummary[]>("/api/v1/dailylog/logs", {
        method: "GET",
        token,
        orgId,
        query: {
          project_id: filters.project_id,
          status: filters.status,
          date_from: filters.date_from,
          date_to: filters.date_to,
          limit: filters.limit ?? 20,
          offset: filters.offset ?? 0,
        },
      });
      return { data: (res.data ?? []) as DailyLogSummary[], meta: res.meta };
    },
  });
}

export function useDailyLog(id: string | undefined) {
  const { token, orgId } = useSession();
  return useQuery({
    enabled: Boolean(id),
    queryKey: id ? dailylogKeys.detail(id) : ["dailylog", "noop"],
    queryFn: async () => {
      const res = await apiFetch<DailyLogDetail>(
        `/api/v1/dailylog/logs/${id}`,
        { method: "GET", token, orgId },
      );
      return res.data as DailyLogDetail;
    },
  });
}

export function useCreateDailyLog() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: CreateDailyLogRequest) => {
      const res = await apiFetch<DailyLogSummary>("/api/v1/dailylog/logs", {
        method: "POST",
        token,
        orgId,
        body: payload,
      });
      return res.data as DailyLogSummary;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: dailylogKeys.all }),
  });
}

export function useUpdateDailyLog(logId: string) {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: UpdateDailyLogRequest) => {
      const res = await apiFetch<{ id: string }>(
        `/api/v1/dailylog/logs/${logId}`,
        { method: "PATCH", token, orgId, body: payload },
      );
      return res.data;
    },
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: dailylogKeys.detail(logId) }),
  });
}

export function useTriggerExtract(logId: string) {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation<
    { log_id: string; observations: Observation[] } | null,
    Error,
    boolean | undefined
  >({
    mutationFn: async (force) => {
      const res = await apiFetch<{ log_id: string; observations: Observation[] }>(
        `/api/v1/dailylog/logs/${logId}/extract`,
        { method: "POST", token, orgId, body: { force: force ?? false } },
      );
      return res.data;
    },
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: dailylogKeys.detail(logId) }),
  });
}

export function usePatterns(
  projectId: string | undefined,
  dateFrom: string,
  dateTo: string,
) {
  const { token, orgId } = useSession();
  return useQuery({
    enabled: Boolean(projectId),
    queryKey: projectId
      ? dailylogKeys.patterns(projectId, { dateFrom, dateTo })
      : ["dailylog", "patterns", "noop"],
    queryFn: async () => {
      const res = await apiFetch<PatternsResponse>(
        `/api/v1/dailylog/projects/${projectId}/patterns`,
        {
          method: "GET",
          token,
          orgId,
          query: { date_from: dateFrom, date_to: dateTo },
        },
      );
      return res.data as PatternsResponse;
    },
  });
}

export type {
  DailyLogDetail,
  DailyLogSummary,
  Observation,
  PatternsResponse,
};
