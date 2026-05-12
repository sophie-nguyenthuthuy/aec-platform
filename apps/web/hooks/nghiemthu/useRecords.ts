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
  AcceptanceDetail,
  AcceptanceLevel,
  AcceptanceRecord,
  AcceptanceStatus,
  FinalizeResult,
  QuantityRow,
  RecordSummary,
  SignatoryDecision,
  SignatoryRole,
} from "@aec/ui/nghiemthu";
import { nghiemthuKeys } from "./keys";

export interface RecordListFilters {
  project_id?: string;
  level?: AcceptanceLevel;
  status?: AcceptanceStatus;
  work_item_code?: string;
  limit?: number;
  offset?: number;
}

export interface CreateRecordRequest {
  project_id: string;
  reference_no: string;
  acceptance_level: AcceptanceLevel;
  title: string;
  acceptance_date: string;
  location?: string;
  work_item_codes?: string[];
  quantities?: QuantityRow[];
  basis?: Record<string, unknown>;
  conclusion?: string;
}

export interface AddSignatoryRequest {
  role: SignatoryRole;
  org_name: string;
  representative_name: string;
  position?: string;
  required?: boolean;
  sort_order?: number;
}

export interface SignRequest {
  decision: SignatoryDecision;
  comment?: string;
  signed_at?: string;
  signature_file_id?: string;
}

export function useRecords(filters: RecordListFilters = {}) {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: nghiemthuKeys.records(filters),
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const res = await apiFetch<RecordSummary[]>(
        "/api/v1/nghiemthu/records",
        {
          method: "GET",
          token,
          orgId,
          query: {
            project_id: filters.project_id,
            level: filters.level,
            status: filters.status,
            work_item_code: filters.work_item_code,
            limit: filters.limit ?? 20,
            offset: filters.offset ?? 0,
          },
        },
      );
      return { data: (res.data ?? []) as RecordSummary[], meta: res.meta };
    },
  });
}

export function useRecord(id: string | undefined) {
  const { token, orgId } = useSession();
  return useQuery({
    enabled: Boolean(id),
    queryKey: id ? nghiemthuKeys.record(id) : ["noop"],
    queryFn: async () => {
      const res = await apiFetch<AcceptanceDetail>(
        `/api/v1/nghiemthu/records/${id}`,
        { method: "GET", token, orgId },
      );
      return res.data as AcceptanceDetail;
    },
  });
}

export function useCreateRecord() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationKey: ["nghiemthu", "records", "create"],
    mutationFn: async (payload: CreateRecordRequest) => {
      const res = await apiFetch<AcceptanceRecord>(
        "/api/v1/nghiemthu/records",
        { method: "POST", token, orgId, body: payload },
      );
      return res.data as AcceptanceRecord;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: nghiemthuKeys.all });
    },
  });
}

export function useAddSignatory(recordId: string) {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationKey: ["nghiemthu", "record", recordId, "signatory", "add"],
    mutationFn: async (payload: AddSignatoryRequest) => {
      const res = await apiFetch(
        `/api/v1/nghiemthu/records/${recordId}/signatories`,
        { method: "POST", token, orgId, body: payload },
      );
      return res.data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: nghiemthuKeys.record(recordId) });
      qc.invalidateQueries({ queryKey: nghiemthuKeys.all });
    },
  });
}

export function useSignSignatory(recordId: string) {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationKey: ["nghiemthu", "signatory", "sign"],
    mutationFn: async ({
      signatoryId,
      payload,
    }: {
      signatoryId: string;
      payload: SignRequest;
    }) => {
      const res = await apiFetch(
        `/api/v1/nghiemthu/signatories/${signatoryId}/sign`,
        { method: "POST", token, orgId, body: payload },
      );
      return res.data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: nghiemthuKeys.record(recordId) });
      qc.invalidateQueries({ queryKey: nghiemthuKeys.all });
    },
  });
}

export function useFinalizeRecord(recordId: string) {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationKey: ["nghiemthu", "record", recordId, "finalize"],
    mutationFn: async () => {
      const res = await apiFetch<FinalizeResult>(
        `/api/v1/nghiemthu/records/${recordId}/finalize`,
        { method: "POST", token, orgId },
      );
      return res.data as FinalizeResult;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: nghiemthuKeys.record(recordId) });
      qc.invalidateQueries({ queryKey: nghiemthuKeys.all });
    },
  });
}
