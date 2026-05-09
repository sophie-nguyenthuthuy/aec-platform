"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";


export interface RetentionStat {
  table: string;
  ttl_days: number;
  row_count: number;
  oldest_at: string | null;
  overdue_count: number;
  projected_next_prune_count: number;
  archived_to_s3: boolean;
}


/**
 * Per-table retention metrics for the admin status page. The
 * endpoint is admin-gated, so non-admin viewers will see a 403; the
 * page surfaces that as a friendly hint.
 */
export function useRetentionStatus() {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: ["admin", "retention", "status"],
    queryFn: async () => {
      const res = await apiFetch<RetentionStat[]>("/api/v1/admin/retention/status", {
        method: "GET",
        token,
        orgId,
      });
      return res.data as RetentionStat[];
    },
  });
}


export interface RetentionRunSummary {
  table: string;
  deleted_count: number;
  archive_key?: string | null;
  error?: string;
}


/**
 * On-demand prune. Same logic as the nightly cron, fired manually.
 * Invalidates the status query on success so the dashboard reflects
 * the freshly-emptied tables.
 */
export function useRetentionRunNow() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const res = await apiFetch<{ tables: RetentionRunSummary[] }>(
        "/api/v1/admin/retention/run",
        { method: "POST", token, orgId },
      );
      return res.data as { tables: RetentionRunSummary[] };
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "retention", "status"] });
    },
  });
}
