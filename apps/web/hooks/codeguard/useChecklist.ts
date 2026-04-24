"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";
import type {
  ChecklistItemStatus,
  PermitChecklist,
} from "@aec/ui/codeguard";
import { codeguardKeys } from "./keys";

export interface PermitChecklistRequest {
  project_id: string;
  jurisdiction: string;
  project_type: string;
  parameters?: Record<string, unknown>;
}

export interface MarkItemRequest {
  item_id: string;
  status: ChecklistItemStatus;
  notes?: string;
  assignee_id?: string;
}

export function useGeneratePermitChecklist() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationKey: ["codeguard", "permit-checklist"],
    mutationFn: async (payload: PermitChecklistRequest) => {
      const res = await apiFetch<PermitChecklist>(
        "/api/v1/codeguard/permit-checklist",
        {
          method: "POST",
          token,
          orgId,
          body: payload,
        },
      );
      return res.data as PermitChecklist;
    },
    onSuccess: (data) => {
      qc.setQueryData(codeguardKeys.checklist(data.id), data);
    },
  });
}

export function useMarkChecklistItem(checklistId: string) {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationKey: ["codeguard", "checklist", checklistId, "mark-item"],
    mutationFn: async (payload: MarkItemRequest) => {
      const res = await apiFetch<PermitChecklist>(
        `/api/v1/codeguard/checks/${checklistId}/mark-item`,
        {
          method: "POST",
          token,
          orgId,
          body: payload,
        },
      );
      return res.data as PermitChecklist;
    },
    onSuccess: (data) => {
      qc.setQueryData(codeguardKeys.checklist(data.id), data);
    },
  });
}
