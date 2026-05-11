"use client";

/**
 * Hook for `GET /api/v1/admin/crons` — the static cron-job registry
 * exposed by `routers/cron_admin.py`. In-process read on the backend
 * (no DB), so the response is fast (<5ms) and identical across replicas.
 *
 * Drives `/admin/crons`. Refetch interval is 60s — the registry is
 * effectively static between deploys, but `next_run` shifts forward
 * minute-by-minute and a stale page would mislead operators triaging
 * "what's due to fire next?"
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
} from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";


/** Last-run summary for one cron, sourced from the `cron_runs` table.
 *  Null `last_run` on a `CronEntry` means the cron hasn't fired since
 *  the telemetry decorator was deployed (or since the row was pruned
 *  by retention). */
export interface CronLastRun {
  /** When this run started (ISO-8601). */
  started_at: string | null;
  /** When the run finished, or null while still running. */
  finished_at: string | null;
  /** "running" | "succeeded" | "failed". */
  status: string;
  /** Wall-clock duration, milliseconds. Null while still running. */
  duration_ms: number | null;
  /** Truncated exception text on failure; null on success. */
  error_message: string | null;
  /** True iff status='running' AND elapsed > 3× the cron's rolling
   *  7d p95. Null when the row isn't running (stuck-detection only
   *  applies to in-flight runs). The watchdog Slack-alerts on the
   *  same condition; this surfaces it in the dashboard so ops sees
   *  the flag visually before the alert fires. */
  stuck: boolean | null;
}


/** Mirrors the row shape from `routers/cron_admin.py::list_crons`. */
export interface CronEntry {
  /** arq's auto-derived job name (e.g. "cron:weekly_report_cron"). */
  name: string;
  /** Coroutine function name (e.g. "weekly_report_cron"). */
  function: string;
  /** Module path (e.g. "workers.queue"). */
  module: string;
  /** Human-readable schedule (e.g. "Mondays at 06:00 UTC"). */
  schedule: string;
  /** Next due fire time, ISO-8601, or null when arq's calculate_next
   *  failed (defensively rendered as "—" by the page). */
  next_run: string | null;
  /** First line of the cron function's docstring, truncated to 160
   *  chars. Empty string if the function has no docstring. */
  description: string;
  /** Most recent invocation of this cron, or null if it hasn't fired
   *  yet (or all telemetry has been retention-pruned). */
  last_run: CronLastRun | null;
}


export function useCrons() {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: ["admin", "crons"] as const,
    // Refetch every 60s so the `next_run` countdowns stay roughly
    // accurate without hammering the endpoint. The registry itself
    // doesn't change between deploys; this is for the time-sensitive
    // bits.
    refetchInterval: 60_000,
    queryFn: async () => {
      const res = await apiFetch<CronEntry[]>("/api/v1/admin/crons", {
        method: "GET",
        token,
        orgId,
      });
      return (res.data ?? []) as CronEntry[];
    },
  });
}


/**
 * One row from `cron_runs` for the per-cron history view. Mirrors
 * the dict shape returned by `services.cron_telemetry.recent_runs_for_cron`.
 *
 * Distinct from `CronLastRun` (the registry summary): runs carry an
 * `id` because the drilldown table needs stable React keys, AND the
 * row shape is "one row per invocation" rather than "the latest
 * invocation."
 */
export interface CronRunEntry {
  id: string;
  started_at: string | null;
  finished_at: string | null;
  /** "running" | "succeeded" | "failed" — closed vocabulary, mirrored
   *  in `services/cron_telemetry.py::CronRunStatus`. A drift here
   *  would silently break the dashboard's status-pill rendering. */
  status: string;
  duration_ms: number | null;
  error_message: string | null;
}


/**
 * `GET /api/v1/admin/crons/{cron_name}/runs` — recent invocations of
 * one cron, newest first. Drives the drilldown at
 * `/admin/crons/[cron_name]`.
 *
 * Backend caps at 20 runs per call; the page renders all of them
 * without paging because the cap is small and the row shape is
 * narrow (one fetch is enough to drive the sparkline + table).
 *
 * Refetch interval is 30s — shorter than the registry hook because
 * the drilldown is the page ops opens DURING an incident ("did the
 * cron just retry?"). 30s is still gentle on the DB (capped LIMIT
 * 20 over the (cron_name, started_at DESC) index).
 */
export interface RunNowResponse {
  cron_name: string;
  /** arq job_id — the worker correlates this with its JobResult log. */
  job_id: string;
  /** Always 'enqueued' on success; the eventual cron_runs row carries
   *  the running/succeeded/failed state. */
  status: string;
}


/**
 * `POST /api/v1/admin/crons/{cron_name}/run` — operator-triggered
 * manual run. Closes the incident-triage loop: instead of waiting for
 * the next scheduled tick, an admin can fire the cron now.
 *
 * Behaviour:
 *   * Server enqueues an arq job that re-uses the existing
 *     `cron_telemetry_wrap` decorator, so the manual run writes a
 *     fresh `cron_runs` row (status running → succeeded/failed) just
 *     like a scheduled tick.
 *   * Response carries the arq `job_id` for telemetry correlation;
 *     the new `cron_runs` row appears in the drilldown sparkline
 *     within seconds.
 *   * After mutate, we invalidate the runs hook so the drilldown
 *     refetches in 30s as usual; the operator sees the new row
 *     appear without a manual refresh.
 *   * The drilldown's poll interval (30s) is the upper bound on
 *     visible feedback; for a fast cron the new row often shows up
 *     on the first poll after the click.
 */
export function useRunCronNow(): UseMutationResult<
  RunNowResponse,
  Error,
  string  // cron_name
> {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (cronName) => {
      const encoded = encodeURIComponent(cronName);
      const res = await apiFetch<RunNowResponse>(
        `/api/v1/admin/crons/${encoded}/run`,
        { method: "POST", token, orgId },
      );
      return res.data as RunNowResponse;
    },
    onSuccess: (_data, cronName) => {
      // Invalidate the runs hook so the drilldown sparkline refetches
      // and picks up the new running/succeeded row. Wait 1s — the arq
      // worker hasn't necessarily started the job yet on the same tick.
      setTimeout(() => {
        qc.invalidateQueries({
          queryKey: ["admin", "crons", "runs", cronName],
        });
        qc.invalidateQueries({ queryKey: ["admin", "crons"] });
      }, 1000);
    },
  });
}


export function useCronRuns(cronName: string | undefined) {
  const { token, orgId } = useSession();
  return useQuery({
    enabled: Boolean(cronName),
    queryKey: cronName
      ? (["admin", "crons", "runs", cronName] as const)
      : (["admin", "crons", "runs", "noop"] as const),
    refetchInterval: 30_000,
    queryFn: async () => {
      // Encode the cron name — arq's convention is `cron:<func_name>`,
      // and the colon is a reserved URL char. Without encoding, the
      // path resolves to `/crons/cron:weekly_report_cron/runs` which
      // works in Chrome but is ambiguous on stricter clients.
      const encoded = encodeURIComponent(cronName!);
      const res = await apiFetch<CronRunEntry[]>(
        `/api/v1/admin/crons/${encoded}/runs`,
        { method: "GET", token, orgId },
      );
      return (res.data ?? []) as CronRunEntry[];
    },
  });
}
