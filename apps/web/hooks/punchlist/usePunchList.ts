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
  PunchItem,
  PunchItemStatus,
  PunchList,
  PunchListDetail,
  PunchListStatus,
  PunchSeverity,
  PunchTrade,
} from "@aec/types/punchlist";

import { punchListKeys } from "./keys";

export interface PunchListListFilters {
  project_id?: string;
  status?: PunchListStatus;
  limit?: number;
  offset?: number;
}

export interface CreatePunchListRequest {
  project_id: string;
  name: string;
  walkthrough_date: string;
  owner_attendees?: string;
  notes?: string;
}

export interface AddPunchItemRequest {
  description: string;
  location?: string;
  trade?: PunchTrade;
  severity?: PunchSeverity;
  due_date?: string;
  notes?: string;
  assigned_user_id?: string;
  photo_id?: string;
}

export interface UpdatePunchItemRequest {
  description?: string;
  location?: string;
  trade?: PunchTrade;
  severity?: PunchSeverity;
  status?: PunchItemStatus;
  due_date?: string;
  notes?: string;
  assigned_user_id?: string;
}

export function usePunchLists(filters: PunchListListFilters = {}) {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: punchListKeys.list(filters),
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const res = await apiFetch<PunchList[]>("/api/v1/punchlist/lists", {
        method: "GET",
        token,
        orgId,
        query: {
          project_id: filters.project_id,
          status: filters.status,
          limit: filters.limit ?? 20,
          offset: filters.offset ?? 0,
        },
      });
      return { data: (res.data ?? []) as PunchList[], meta: res.meta };
    },
  });
}

export function usePunchList(id: string | undefined) {
  const { token, orgId } = useSession();
  return useQuery({
    enabled: Boolean(id),
    queryKey: id ? punchListKeys.detail(id) : ["punchlist", "noop"],
    queryFn: async () => {
      const res = await apiFetch<PunchListDetail>(
        `/api/v1/punchlist/lists/${id}`,
        { method: "GET", token, orgId },
      );
      return res.data as PunchListDetail;
    },
  });
}

export function useCreatePunchList() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: CreatePunchListRequest) => {
      const res = await apiFetch<PunchList>("/api/v1/punchlist/lists", {
        method: "POST",
        token,
        orgId,
        body: payload,
      });
      return res.data as PunchList;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: punchListKeys.all }),
  });
}

export function useAddPunchItem(listId: string) {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: AddPunchItemRequest) => {
      const res = await apiFetch<PunchItem>(
        `/api/v1/punchlist/lists/${listId}/items`,
        { method: "POST", token, orgId, body: payload },
      );
      return res.data as PunchItem;
    },
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: punchListKeys.detail(listId) }),
  });
}

export function useUpdatePunchItem(listId: string) {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({
      itemId,
      payload,
    }: {
      itemId: string;
      payload: UpdatePunchItemRequest;
    }) => {
      const res = await apiFetch<PunchItem>(
        `/api/v1/punchlist/items/${itemId}`,
        { method: "PATCH", token, orgId, body: payload },
      );
      return res.data as PunchItem;
    },
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: punchListKeys.detail(listId) }),
  });
}

export interface PhotoHint {
  photo_id: string;
  file_id?: string | null;
  taken_at?: string | null;
  thumbnail_url?: string | null;
  safety_status?: string | null;
  tags: string[];
}

export interface PhotoHintsResponse {
  list_id: string;
  walkthrough_date: string;
  window_days: number;
  results: PhotoHint[];
}

/** SiteEye photos taken near the walkthrough day, for one-click attach. */
export function usePhotoHints(listId: string | undefined) {
  const { token, orgId } = useSession();
  return useQuery({
    enabled: Boolean(listId),
    queryKey: listId
      ? (["punchlist", "photo-hints", listId] as const)
      : (["punchlist", "photo-hints", "noop"] as const),
    staleTime: 30_000,
    queryFn: async () => {
      const res = await apiFetch<PhotoHintsResponse>(
        `/api/v1/punchlist/lists/${listId}/photo-hints`,
        { method: "GET", token, orgId },
      );
      return res.data as PhotoHintsResponse;
    },
  });
}

export function useSignOffPunchList(listId: string) {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation<PunchList, Error, string | undefined>({
    mutationFn: async (notes) => {
      const res = await apiFetch<PunchList>(
        `/api/v1/punchlist/lists/${listId}/sign-off`,
        { method: "POST", token, orgId, body: { notes: notes ?? null } },
      );
      return res.data as PunchList;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: punchListKeys.detail(listId) });
      qc.invalidateQueries({ queryKey: punchListKeys.all });
    },
  });
}

export type { PunchList, PunchListDetail, PunchItem };
