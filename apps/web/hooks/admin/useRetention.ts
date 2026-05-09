"use client";

/**
 * Hook for `GET /api/v1/admin/retention/status` — per-table retention
 * telemetry. Drives `/admin/retention`.
 *
 * The backend's `services.retention.collect_stats` returns one entry
 * per `RETENTION_POLICIES` entry: row count, oldest row age, configured
 * TTL, and how many rows the NEXT prune will delete (capped at the
 * per-run row cap).
 *
 * Refetch interval is 60s — the numbers change slowly (the cron prunes
 * once a day at 03:00 UTC), but a 5-min stale view would show wrong
 * counts to ops watching the cron land.
 *
 * Read-only v1: no per-tenant overrides, no manual edit. The "run
 * now" button is wired separately via `useRetentionRunNow` so the
 * button + the table can render independently.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
} from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";


/** One row per managed table. Mirrors the dict shape from
 *  `services.retention.collect_stats`. */
export interface RetentionStatusRow {
  /** Postgres table name (e.g. "audit_events"). */
  table: string;
  /** TTL in days — rows older than this are eligible for prune. */
  ttl_days: number;
  /** Total row count right now. */
  row_count: number;
  /** ISO-8601 timestamp of the oldest row (or null if empty). */
  oldest_at: string | null;
  /** Number of rows currently older than ttl_days — what the next
   *  cron tick would prune (uncapped). */
  overdue_count: number;
  /** Capped at the per-run row cap. The cron deletes at most this
   *  many on its next tick; if `overdue_count` is larger, the
   *  remainder catches up over multiple ticks. */
  projected_next_prune_count: number;
  /** True iff the policy archives deleted rows to S3 before the
   *  DELETE commits. False for pure-telemetry tables where the
   *  archive cost outweighs the recovery value. */
  archived_to_s3: boolean;
}


export function useRetentionStatus() {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: ["admin", "retention", "status"] as const,
    refetchInterval: 60_000,
    queryFn: async () => {
      const res = await apiFetch<RetentionStatusRow[]>(
        "/api/v1/admin/retention/status",
        { method: "GET", token, orgId },
      );
      return (res.data ?? []) as RetentionStatusRow[];
    },
  });
}


export interface RetentionRunResponse {
  /** One summary per table — same shape as the cron's per-table
   *  result. `error` is set on per-table failure (the rest of the
   *  run continues). */
  tables: Array<{
    table: string;
    deleted_count: number;
    error?: string;
    archive_key?: string | null;
  }>;
}


/**
 * `POST /api/v1/admin/retention/run` — fire the retention prune job
 * NOW instead of waiting for the 03:00 UTC cron tick.
 *
 * Useful for: (1) initial cleanup after deploying retention to a
 * long-lived org with years of audit history; (2) reproducing a cron
 * failure with the operator watching the logs.
 *
 * Bounded by the same per-run row cap as the scheduled cron, so a
 * single click won't lock any one table for minutes.
 */
export function useRetentionRunNow(): UseMutationResult<
  RetentionRunResponse,
  Error,
  void
> {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const res = await apiFetch<RetentionRunResponse>(
        "/api/v1/admin/retention/run",
        { method: "POST", token, orgId },
      );
      return res.data as RetentionRunResponse;
    },
    onSuccess: () => {
      // Refetch the status table so the row counts shift to reflect
      // the just-completed prune.
      qc.invalidateQueries({ queryKey: ["admin", "retention", "status"] });
    },
  });
}
