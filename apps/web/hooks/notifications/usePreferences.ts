"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";
import type { ISODate, UUID } from "@aec/types/envelope";

/**
 * Per-user, per-org opt-in for an alert kind. Mirrors
 * `apps/api/schemas/notifications.py::NotificationPreferenceOut`.
 *
 * `id` is `00000000-0000-0000-0000-000000000000` for keys the user
 * hasn't touched yet — the server pre-fills the response with every
 * known key so the UI can render every switch without a probe-then-
 * create dance.
 */
export interface NotificationPreference {
  id: UUID;
  key: string;
  email_enabled: boolean;
  slack_enabled: boolean;
  /** ISODate for persisted rows, null for synthetic prefilled defaults. */
  updated_at: ISODate | null;
}

const prefKeys = {
  all: ["notifications", "preferences"] as const,
};

export function usePreferences() {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: prefKeys.all,
    queryFn: async () => {
      const res = await apiFetch<NotificationPreference[]>(
        "/api/v1/notifications/preferences",
        { token, orgId },
      );
      return res.data ?? [];
    },
  });
}


export interface UpsertPreferenceInput {
  key: string;
  /** Either omit to leave unchanged, or pass true/false to set explicitly. */
  email_enabled?: boolean;
  /** Same shape as `email_enabled` — independent channels. */
  slack_enabled?: boolean;
}


export function useUpsertPreference() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (input: UpsertPreferenceInput) => {
      const res = await apiFetch<NotificationPreference>(
        `/api/v1/notifications/preferences/${encodeURIComponent(input.key)}`,
        {
          method: "PUT",
          body: {
            email_enabled: input.email_enabled,
            slack_enabled: input.slack_enabled,
          },
          token,
          orgId,
        },
      );
      if (!res.data) throw new Error("Empty response");
      return res.data;
    },
    onSuccess: () => {
      // Re-fetch the full list so the UI's switch state stays in sync
      // with what the server now believes.
      void qc.invalidateQueries({ queryKey: prefKeys.all });
    },
  });
}
