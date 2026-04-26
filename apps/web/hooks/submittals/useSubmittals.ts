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
  RfiResponseDraft,
  RfiSimilarResponse,
  Submittal,
  SubmittalDetail,
  SubmittalStatus,
  SubmittalType,
  SubmittalRevision,
  RevisionStatus,
  BallInCourt,
} from "@aec/types/submittals";

import { submittalsKeys } from "./keys";

export interface SubmittalListFilters {
  project_id?: string;
  status?: SubmittalStatus;
  ball_in_court?: BallInCourt;
  csi_division?: string;
  limit?: number;
  offset?: number;
}

export interface CreateSubmittalRequest {
  project_id: string;
  title: string;
  description?: string;
  submittal_type?: SubmittalType;
  spec_section?: string;
  csi_division?: string;
  package_number?: string;
  contractor_id?: string;
  due_date?: string;
  notes?: string;
  file_id?: string;
}

export interface ReviewRevisionRequest {
  review_status: RevisionStatus;
  reviewer_notes?: string;
  annotations?: Record<string, unknown>[];
}

export function useSubmittals(filters: SubmittalListFilters = {}) {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: submittalsKeys.list(filters),
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const res = await apiFetch<Submittal[]>("/api/v1/submittals", {
        method: "GET",
        token,
        orgId,
        query: {
          project_id: filters.project_id,
          status: filters.status,
          ball_in_court: filters.ball_in_court,
          csi_division: filters.csi_division,
          limit: filters.limit ?? 20,
          offset: filters.offset ?? 0,
        },
      });
      return { data: (res.data ?? []) as Submittal[], meta: res.meta };
    },
  });
}

export function useSubmittal(id: string | undefined) {
  const { token, orgId } = useSession();
  return useQuery({
    enabled: Boolean(id),
    queryKey: id ? submittalsKeys.detail(id) : ["submittals", "noop"],
    queryFn: async () => {
      const res = await apiFetch<SubmittalDetail>(
        `/api/v1/submittals/${id}`,
        { method: "GET", token, orgId },
      );
      return res.data as SubmittalDetail;
    },
  });
}

export function useCreateSubmittal() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: CreateSubmittalRequest) => {
      const res = await apiFetch<Submittal>("/api/v1/submittals", {
        method: "POST",
        token,
        orgId,
        body: payload,
      });
      return res.data as Submittal;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: submittalsKeys.all }),
  });
}

export function useReviewRevision(submittalId: string) {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({
      revisionId,
      payload,
    }: {
      revisionId: string;
      payload: ReviewRevisionRequest;
    }) => {
      const res = await apiFetch<SubmittalRevision>(
        `/api/v1/submittals/revisions/${revisionId}/review`,
        { method: "POST", token, orgId, body: payload },
      );
      return res.data as SubmittalRevision;
    },
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: submittalsKeys.detail(submittalId) }),
  });
}

// ---- RFI AI ----

export function useFindSimilarRfis(rfiId: string | undefined) {
  const { token, orgId } = useSession();
  return useMutation<RfiSimilarResponse, Error, { limit?: number; max_distance?: number }>({
    mutationFn: async ({ limit = 5, max_distance = 0.5 }) => {
      const res = await apiFetch<RfiSimilarResponse>(
        `/api/v1/submittals/rfis/${rfiId}/similar`,
        { method: "POST", token, orgId, body: { limit, max_distance } },
      );
      return res.data as RfiSimilarResponse;
    },
  });
}

export function useDraftRfiResponse(rfiId: string | undefined) {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation<RfiResponseDraft, Error, { cache_minutes?: number; retrieval_k?: number } | undefined>({
    mutationFn: async (opts) => {
      const res = await apiFetch<RfiResponseDraft>(
        `/api/v1/submittals/rfis/${rfiId}/draft`,
        {
          method: "POST",
          token,
          orgId,
          body: {
            cache_minutes: opts?.cache_minutes ?? 60,
            retrieval_k: opts?.retrieval_k ?? 6,
          },
        },
      );
      return res.data as RfiResponseDraft;
    },
    onSuccess: () =>
      rfiId &&
      qc.invalidateQueries({ queryKey: submittalsKeys.rfiDraft(rfiId) }),
  });
}

export function useAcceptDraft() {
  const { token, orgId } = useSession();
  return useMutation<RfiResponseDraft, Error, { draftId: string; notes?: string }>({
    mutationFn: async ({ draftId, notes }) => {
      const res = await apiFetch<RfiResponseDraft>(
        `/api/v1/submittals/drafts/${draftId}/accept`,
        { method: "POST", token, orgId, body: { notes } },
      );
      return res.data as RfiResponseDraft;
    },
  });
}

export type {
  Submittal,
  SubmittalDetail,
  SubmittalRevision,
  RfiResponseDraft,
  RfiSimilarResponse,
};
