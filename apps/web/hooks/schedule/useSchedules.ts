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
  Activity,
  Dependency,
  RiskAssessment,
  ScheduleDetail,
  ScheduleStatus,
  ScheduleSummary,
} from "@aec/types/schedulepilot";

import { scheduleKeys } from "./keys";

export interface ScheduleListFilters {
  project_id?: string;
  status?: ScheduleStatus;
  limit?: number;
  offset?: number;
}

export interface CreateScheduleRequest {
  project_id: string;
  name: string;
  notes?: string;
  data_date?: string;
}

export interface CreateActivityRequest {
  code: string;
  name: string;
  activity_type?: "task" | "milestone" | "summary";
  planned_start?: string;
  planned_finish?: string;
  planned_duration_days?: number;
  notes?: string;
  sort_order?: number;
}

export interface UpdateActivityRequest {
  name?: string;
  planned_start?: string;
  planned_finish?: string;
  planned_duration_days?: number;
  actual_start?: string;
  actual_finish?: string;
  percent_complete?: number;
  status?: "not_started" | "in_progress" | "complete" | "on_hold";
  notes?: string;
  sort_order?: number;
}

export function useSchedules(filters: ScheduleListFilters = {}) {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: scheduleKeys.lists(filters),
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const res = await apiFetch<ScheduleSummary[]>(
        "/api/v1/schedule/schedules",
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
      return {
        data: (res.data ?? []) as ScheduleSummary[],
        meta: res.meta,
      };
    },
  });
}

export function useSchedule(id: string | undefined) {
  const { token, orgId } = useSession();
  return useQuery({
    enabled: Boolean(id),
    queryKey: id ? scheduleKeys.detail(id) : ["schedule", "noop"],
    queryFn: async () => {
      const res = await apiFetch<ScheduleDetail>(
        `/api/v1/schedule/schedules/${id}`,
        { method: "GET", token, orgId },
      );
      return res.data as ScheduleDetail;
    },
  });
}

export function useCreateSchedule() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: CreateScheduleRequest) => {
      const res = await apiFetch<ScheduleSummary>(
        "/api/v1/schedule/schedules",
        { method: "POST", token, orgId, body: payload },
      );
      return res.data as ScheduleSummary;
    },
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: scheduleKeys.all }),
  });
}

export function useBaseline(scheduleId: string) {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (note?: string) => {
      const res = await apiFetch<ScheduleSummary>(
        `/api/v1/schedule/schedules/${scheduleId}/baseline`,
        { method: "POST", token, orgId, body: { note } },
      );
      return res.data as ScheduleSummary;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: scheduleKeys.detail(scheduleId) });
      qc.invalidateQueries({ queryKey: scheduleKeys.all });
    },
  });
}

export function useCreateActivity(scheduleId: string) {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: CreateActivityRequest) => {
      const res = await apiFetch<Activity>(
        `/api/v1/schedule/schedules/${scheduleId}/activities`,
        { method: "POST", token, orgId, body: payload },
      );
      return res.data as Activity;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: scheduleKeys.detail(scheduleId) }),
  });
}

export function useUpdateActivity(scheduleId: string, activityId: string) {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: UpdateActivityRequest) => {
      const res = await apiFetch<Activity>(
        `/api/v1/schedule/activities/${activityId}`,
        { method: "PATCH", token, orgId, body: payload },
      );
      return res.data as Activity;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: scheduleKeys.detail(scheduleId) }),
  });
}

export function useRunRiskAssessment(scheduleId: string) {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation<RiskAssessment, Error, boolean | undefined>({
    mutationFn: async (force) => {
      const res = await apiFetch<RiskAssessment>(
        `/api/v1/schedule/schedules/${scheduleId}/risk-assessment`,
        { method: "POST", token, orgId, body: { force: force ?? false } },
      );
      return res.data as RiskAssessment;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: scheduleKeys.detail(scheduleId) });
      qc.invalidateQueries({ queryKey: scheduleKeys.riskAssessments(scheduleId) });
    },
  });
}

// Re-export the underlying types for page-level convenience.
export type {
  Activity,
  Dependency,
  RiskAssessment,
  ScheduleDetail,
  ScheduleSummary,
};
