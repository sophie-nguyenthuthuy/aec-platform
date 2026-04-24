"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";
import type {
  CloseoutCategory,
  CloseoutItem,
  CloseoutStatus,
} from "@aec/ui/handover";
import { handoverKeys } from "./keys";

export interface CreateCloseoutItemRequest {
  category: CloseoutCategory;
  title: string;
  description?: string;
  required?: boolean;
  sort_order?: number;
}

export interface UpdateCloseoutItemRequest {
  status?: CloseoutStatus;
  assignee_id?: string;
  notes?: string;
  file_ids?: string[];
}

export function useCreateCloseoutItem(packageId: string) {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationKey: ["handover", "closeout-items", packageId, "create"],
    mutationFn: async (payload: CreateCloseoutItemRequest) => {
      const res = await apiFetch<CloseoutItem>(
        `/api/v1/handover/packages/${packageId}/closeout-items`,
        { method: "POST", token, orgId, body: payload },
      );
      return res.data as CloseoutItem;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: handoverKeys.package(packageId) });
    },
  });
}

export function useUpdateCloseoutItem(packageId: string) {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationKey: ["handover", "closeout-items", packageId, "update"],
    mutationFn: async (args: {
      item_id: string;
      patch: UpdateCloseoutItemRequest;
    }) => {
      const res = await apiFetch<CloseoutItem>(
        `/api/v1/handover/closeout-items/${args.item_id}`,
        { method: "PATCH", token, orgId, body: args.patch },
      );
      return res.data as CloseoutItem;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: handoverKeys.package(packageId) });
    },
  });
}
