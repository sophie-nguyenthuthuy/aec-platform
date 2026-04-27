"use client";

import { useMemo } from "react";
import type { ScraperRun } from "@aec/types";

interface ScraperRunsPanelProps {
  runs: ScraperRun[];
  isLoading?: boolean;
  error?: { message: string } | null;
  className?: string;
}

/**
 * Drift-monitoring panel for the prices page.
 *
 * Surfaces three pieces ops actually look at when triaging:
 *   1. Which provincial scrapes failed (red dot, hover for error).
 *   2. Which succeeded but with high `unmatched/scraped` ratio (drift).
 *   3. Recent runs in time order — useful for "did the cron fire today?"
 *
 * Sorting: most-recent-first; the API already sorts by `started_at DESC`.
 * We don't re-sort in the client because the server-side order also
 * encodes the order in which scrapers ran, which is information the
 * raw timestamp loses when many runs land within the same second.
 */
export function ScraperRunsPanel({
  runs,
  isLoading,
  error,
  className = "",
}: ScraperRunsPanelProps): JSX.Element {
  const counts = useMemo(() => summarise(runs), [runs]);

  return (
    <section className={`overflow-hidden rounded-lg border border-slate-200 bg-white ${className}`}>
      <header className="flex items-baseline justify-between border-b border-slate-100 px-4 py-2">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-700">
          Scraper runs
        </h3>
        <p className="text-xs text-slate-500">
          {counts.total === 0
            ? "no runs"
            : `${counts.ok} ok · ${counts.failed} failed · ${counts.drifting} drifting`}
        </p>
      </header>

      {isLoading ? (
        <div className="px-4 py-6 text-sm text-slate-500">Loading…</div>
      ) : error ? (
        <div className="px-4 py-6 text-sm text-red-600">{error.message}</div>
      ) : runs.length === 0 ? (
        <div className="px-4 py-6 text-sm text-slate-500">
          No scraper runs yet. The monthly cron will populate this once it fires.
        </div>
      ) : (
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-600">
            <tr>
              <th className="px-3 py-2">Slug</th>
              <th className="px-3 py-2">Started</th>
              <th className="px-3 py-2 text-right">Scraped</th>
              <th className="px-3 py-2 text-right">Unmatched</th>
              <th className="px-3 py-2">Status</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => (
              <RunRow key={run.id} run={run} />
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}


function RunRow({ run }: { run: ScraperRun }): JSX.Element {
  const ratio = run.scraped > 0 ? run.unmatched / run.scraped : null;
  // Match the API's drift threshold (services.price_scrapers._DRIFT_THRESHOLD).
  // Keeping it client-side is OK because the ratio is the source of truth
  // — changing the server constant doesn't change what's true on the wire,
  // only the threshold at which we flag a colour.
  const isDrifting = ratio != null && ratio >= 0.3;
  const startedAt = new Date(run.started_at).toLocaleString();

  // Truncate the unmatched sample to 3 names — full list is available
  // by clicking through to the (future) per-run detail page; the
  // panel exists to surface "is this trending bad?", not to be the
  // exhaustive forensic view.
  const sample = run.unmatched_sample.slice(0, 3).join(", ");

  return (
    <tr className="border-t border-slate-100">
      <td className="px-3 py-2 font-mono text-xs text-slate-700">{run.slug}</td>
      <td className="px-3 py-2 text-xs text-slate-500">{startedAt}</td>
      <td className="px-3 py-2 text-right">{run.scraped}</td>
      <td className="px-3 py-2 text-right">
        <span className={isDrifting ? "font-semibold text-amber-700" : "text-slate-700"}>
          {run.unmatched}
          {ratio != null ? (
            <span className="ml-1 text-xs text-slate-500">({Math.round(ratio * 100)}%)</span>
          ) : null}
        </span>
      </td>
      <td className="px-3 py-2">
        <StatusBadge run={run} drifting={isDrifting} />
        {run.error ? (
          <p className="mt-0.5 text-xs text-red-600" title={run.error}>
            {truncate(run.error, 80)}
          </p>
        ) : isDrifting && sample ? (
          <p className="mt-0.5 text-xs text-amber-700" title={run.unmatched_sample.join("\n")}>
            {sample}
            {run.unmatched_sample.length > 3 ? "…" : ""}
          </p>
        ) : null}
      </td>
    </tr>
  );
}


function StatusBadge({
  run,
  drifting,
}: {
  run: ScraperRun;
  drifting: boolean;
}): JSX.Element {
  if (!run.ok) {
    return <Badge tone="red">Failed</Badge>;
  }
  if (drifting) {
    return <Badge tone="amber">Drift</Badge>;
  }
  return <Badge tone="green">OK</Badge>;
}


function Badge({
  tone,
  children,
}: {
  tone: "green" | "amber" | "red";
  children: React.ReactNode;
}): JSX.Element {
  const styles: Record<"green" | "amber" | "red", string> = {
    green: "border-green-200 bg-green-50 text-green-700",
    amber: "border-amber-200 bg-amber-50 text-amber-700",
    red: "border-red-200 bg-red-50 text-red-700",
  };
  return (
    <span className={`inline-block rounded-full border px-2 py-0.5 text-xs font-medium ${styles[tone]}`}>
      {children}
    </span>
  );
}


function summarise(runs: ScraperRun[]) {
  let ok = 0;
  let failed = 0;
  let drifting = 0;
  for (const r of runs) {
    if (!r.ok) {
      failed += 1;
      continue;
    }
    if (r.scraped > 0 && r.unmatched / r.scraped >= 0.3) {
      drifting += 1;
      continue;
    }
    ok += 1;
  }
  return { total: runs.length, ok, failed, drifting };
}


function truncate(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}
