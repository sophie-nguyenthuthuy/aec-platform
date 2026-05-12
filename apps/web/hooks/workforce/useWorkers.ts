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
  ContributionBreakdown,
  EmploymentType,
  SafetyGroup,
  Worker,
  WorkerStatus,
  WorkerSummary,
  WorkforceAlert,
} from "@aec/ui/workforce";
import { workforceKeys } from "./keys";

export interface WorkerListFilters {
  project_id?: string;
  trade?: string;
  status?: WorkerStatus;
  nationality?: string;
  q?: string;
  limit?: number;
  offset?: number;
}

export interface CreateWorkerRequest {
  full_name: string;
  trade: string;
  employment_type?: EmploymentType;
  id_no?: string;
  phone?: string;
  address?: string;
  nationality?: string;
  hire_date?: string;
  employer_org_name?: string;
}

export interface RecordTrainingRequest {
  group: SafetyGroup;
  training_org: string;
  training_date: string;
  valid_until?: string;
  certificate_no?: string;
}

export interface EnrollInsuranceRequest {
  basic_salary_vnd: number;
  bhxh_enrolled?: boolean;
  bhyt_enrolled?: boolean;
  bhtn_enrolled?: boolean;
  bhxh_no?: string;
  enrolled_at?: string;
}

export function useWorkers(filters: WorkerListFilters = {}) {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: workforceKeys.workers(filters),
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const res = await apiFetch<WorkerSummary[]>(
        "/api/v1/workforce/workers",
        {
          method: "GET",
          token,
          orgId,
          query: {
            project_id: filters.project_id,
            trade: filters.trade,
            status: filters.status,
            nationality: filters.nationality,
            q: filters.q,
            limit: filters.limit ?? 20,
            offset: filters.offset ?? 0,
          },
        },
      );
      return { data: (res.data ?? []) as WorkerSummary[], meta: res.meta };
    },
  });
}

export function useCreateWorker() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationKey: ["workforce", "workers", "create"],
    mutationFn: async (payload: CreateWorkerRequest) => {
      const res = await apiFetch<Worker>("/api/v1/workforce/workers", {
        method: "POST",
        token,
        orgId,
        body: payload,
      });
      return res.data as Worker;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: workforceKeys.all });
    },
  });
}

export function useRecordTraining(workerId: string) {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationKey: ["workforce", "worker", workerId, "training"],
    mutationFn: async (payload: RecordTrainingRequest) => {
      const res = await apiFetch(
        `/api/v1/workforce/workers/${workerId}/training`,
        { method: "POST", token, orgId, body: payload },
      );
      return res.data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: workforceKeys.worker(workerId) });
      qc.invalidateQueries({ queryKey: workforceKeys.all });
    },
  });
}

export function useEnrollInsurance(workerId: string) {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationKey: ["workforce", "worker", workerId, "insurance"],
    mutationFn: async (payload: EnrollInsuranceRequest) => {
      const res = await apiFetch(
        `/api/v1/workforce/workers/${workerId}/insurance`,
        { method: "POST", token, orgId, body: payload },
      );
      return res.data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: workforceKeys.worker(workerId) });
      qc.invalidateQueries({ queryKey: workforceKeys.contribution(workerId) });
    },
  });
}

export function useContribution(workerId: string | undefined) {
  const { token, orgId } = useSession();
  return useQuery({
    enabled: Boolean(workerId),
    queryKey: workerId ? workforceKeys.contribution(workerId) : ["noop"],
    queryFn: async () => {
      const res = await apiFetch<ContributionBreakdown>(
        `/api/v1/workforce/workers/${workerId}/insurance/contribution`,
        { method: "GET", token, orgId },
      );
      return res.data as ContributionBreakdown;
    },
  });
}

export function useWorkforceAlerts(expiringWithinDays = 60) {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: workforceKeys.alerts({ expiring_within_days: expiringWithinDays }),
    queryFn: async () => {
      const res = await apiFetch<WorkforceAlert[]>(
        "/api/v1/workforce/alerts",
        {
          method: "GET",
          token,
          orgId,
          query: { expiring_within_days: expiringWithinDays },
        },
      );
      return (res.data ?? []) as WorkforceAlert[];
    },
  });
}
