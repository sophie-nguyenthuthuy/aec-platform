"use client";

/**
 * Admin-only dashboard for the scraper-drift telemetry.
 *
 * Two surfaces:
 *   1. Per-slug summary table over a configurable lookback window —
 *      most-degraded slugs first.
 *   2. Recent-runs list (the same `<ScraperRunsPanel>` mounted on the
 *      prices page, but full-width and unfiltered).
 *
 * Server-side `require_role("admin")` gates both API endpoints; the
 * page itself just renders an "admin only" empty state for non-admins
 * so a misclick on the URL doesn't 403 with no copy.
 */

import Link from "next/link";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { ScraperRunsPanel } from "@aec/ui/costpulse";
import {
  type ScraperRunsSummaryRow,
  useScraperRuns,
  useScraperRunsSummary,
} from "@/hooks/admin";
import { useSession } from "@/lib/auth-context";

import { Sparkline } from "./_components/Sparkline";


export default function ScrapersDashboardPage(): JSX.Element {
  const t = useTranslations("admin_scrapers");
  const session = useSession();
  const isAdmin = session.orgs.find((o) => o.id === session.orgId)?.role === "admin";

  const [windowDays, setWindowDays] = useState(30);
  const summary = useScraperRunsSummary(windowDays);
  const runs = useScraperRuns({ limit: 30 });

  // Window options localised — keys mirror `vi/en.json::admin_scrapers.window_*`.
  const WINDOW_OPTIONS: Array<{ days: number; key: "window_7" | "window_30" | "window_90" }> = [
    { days: 7, key: "window_7" },
    { days: 30, key: "window_30" },
    { days: 90, key: "window_90" },
  ];

  if (!isAdmin) {
    return (
      <div className="mx-auto max-w-3xl p-6">
        <div className="rounded-lg border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">
          {t("non_admin_message")}
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-6">
      <header className="flex items-baseline justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">{t("title")}</h1>
          <p className="text-sm text-slate-500">{t("description")}</p>
        </div>
        <div className="flex items-center gap-3 text-xs">
          {/* Cross-link to the rules editor — when ops see drift in
              the table below, the next click is usually "go fix the
              rule that's missing." */}
          <Link
            href="/admin/normalizer-rules"
            className="text-slate-700 underline hover:text-slate-900"
          >
            {t("link_normalizer_rules")}
          </Link>
        </div>
        <div className="flex gap-1 text-xs">
          {WINDOW_OPTIONS.map((opt) => (
            <button
              key={opt.days}
              type="button"
              onClick={() => setWindowDays(opt.days)}
              className={`rounded-full border px-3 py-1 ${
                windowDays === opt.days
                  ? "border-slate-900 bg-slate-900 text-white"
                  : "border-slate-200 bg-white text-slate-600 hover:bg-slate-100"
              }`}
            >
              {t(opt.key)}
            </button>
          ))}
        </div>
      </header>

      <SummaryTable summary={summary.data ?? []} isLoading={summary.isLoading} t={t} />

      <ScraperRunsPanel
        runs={runs.data ?? []}
        isLoading={runs.isLoading}
        error={runs.error}
      />
    </div>
  );
}


function SummaryTable({
  summary,
  isLoading,
  t,
}: {
  summary: ScraperRunsSummaryRow[];
  isLoading: boolean;
  t: ReturnType<typeof useTranslations<"admin_scrapers">>;
}): JSX.Element {
  return (
    <section className="overflow-hidden rounded-lg border border-slate-200 bg-white">
      <header className="flex items-baseline justify-between border-b border-slate-100 px-4 py-2">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-700">
          {t("summary_heading")}
        </h2>
        <p className="text-xs text-slate-500">
          {t("summary_subheading", { count: summary.length })}
        </p>
      </header>
      {isLoading ? (
        <div className="px-4 py-6 text-sm text-slate-500">{t("loading")}</div>
      ) : summary.length === 0 ? (
        <div className="px-4 py-6 text-sm text-slate-500">{t("empty_state")}</div>
      ) : (
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-600">
            <tr>
              <th className="px-3 py-2">{t("col_slug")}</th>
              <th className="px-3 py-2 text-right">{t("col_runs")}</th>
              <th className="px-3 py-2 text-right">{t("col_failure_rate")}</th>
              <th className="px-3 py-2 text-right">{t("col_avg_drift")}</th>
              {/* Sparkline cell — visible-but-not-headed because the
                  trend is implicitly "drift over the window" already
                  named by `col_avg_drift`. Adding a header would
                  duplicate without informing. */}
              <th className="px-3 py-2">{t("col_trend")}</th>
              <th className="px-3 py-2">{t("col_last_run")}</th>
            </tr>
          </thead>
          <tbody>
            {summary.map((row) => (
              <SummaryRow key={row.slug} row={row} t={t} />
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}


function SummaryRow({
  row,
  t,
}: {
  row: ScraperRunsSummaryRow;
  t: ReturnType<typeof useTranslations<"admin_scrapers">>;
}): JSX.Element {
  // Mirror the same threshold the API uses (`_DRIFT_THRESHOLD = 0.30`)
  // so the dashboard's amber matches the email/log boundary. The
  // failure-rate threshold is "any" — even one failure deserves
  // attention since runs are infrequent.
  const isDrifting = row.avg_drift != null && row.avg_drift >= 0.3;
  const hasFailed = row.failure_rate != null && row.failure_rate > 0;
  const lastRunStale =
    row.last_run_at != null &&
    Date.now() - new Date(row.last_run_at).getTime() > 1000 * 60 * 60 * 24 * 35;

  return (
    <tr className="border-t border-slate-100">
      <td className="px-3 py-2 font-mono text-slate-700">{row.slug}</td>
      <td className="px-3 py-2 text-right">{row.total_runs}</td>
      <td className="px-3 py-2 text-right">
        <span className={hasFailed ? "font-semibold text-red-700" : "text-slate-700"}>
          {row.failure_rate != null
            ? `${Math.round(row.failure_rate * 100)}%`
            : "—"}
        </span>
      </td>
      <td className="px-3 py-2 text-right">
        <span
          className={
            isDrifting ? "font-semibold text-amber-700" : "text-slate-700"
          }
        >
          {row.avg_drift != null
            ? `${Math.round(row.avg_drift * 100)}%`
            : "—"}
        </span>
      </td>
      <td className="px-3 py-2">
        <Sparkline points={row.points} threshold={0.3} />
      </td>
      <td className="px-3 py-2">
        <div className="text-xs text-slate-700">
          {row.last_run_at
            ? new Date(row.last_run_at).toLocaleDateString()
            : "—"}
        </div>
        {row.last_run_ok === false ? (
          <div className="text-xs text-red-700">{t("last_run_failed")}</div>
        ) : null}
        {lastRunStale ? (
          <div className="text-xs text-amber-700">{t("stale_warning")}</div>
        ) : null}
      </td>
    </tr>
  );
}


// ---------- Sparkline ----------
//
// Inline SVG sparkline rendered per-row. We reach for raw SVG (vs a
// chart lib like recharts) because:
//   * One sparkline per row × dozens of rows = a lib's wrapper cost
//     dominates. Raw paths are ~50 lines and zero deps.
//   * A 14–30 point series doesn't need axes, tooltips, or animation —
//     just a polyline + a threshold marker.
//   * Server already returns the points pre-sorted; nothing to compute
//     beyond x/y normalisation.

const SPARKLINE_W = 80;
const SPARKLINE_H = 22;


function Sparkline({
  points,
  threshold,
}: {
  points: ScraperRunsSummaryPoint[];
  /**
   * Drift threshold (e.g. 0.3 == 30%). When any point is at-or-above,
   * the line tints amber and a horizontal dashed line is drawn at the
   * threshold so ops can see "this slug crossed the line on day X."
   */
  threshold: number;
}): JSX.Element {
  // Filter out null-ratio points (runs with scraped=0 — division by
  // zero). Showing them as gaps would require a polyline-per-segment;
  // for a sparkline the simpler "skip" is fine since they're rare.
  const valid = points.filter((p): p is ScraperRunsSummaryPoint & { ratio: number } => p.ratio !== null);

  if (valid.length === 0) {
    // No usable points (slug has only zero-row runs in the window).
    // Render a flat dim baseline so the column doesn't visually
    // collapse — preserves table alignment.
    return (
      <svg width={SPARKLINE_W} height={SPARKLINE_H} aria-hidden="true">
        <line
          x1={0}
          y1={SPARKLINE_H / 2}
          x2={SPARKLINE_W}
          y2={SPARKLINE_H / 2}
          stroke="rgb(203 213 225)"
          strokeWidth={1}
          strokeDasharray="2 2"
        />
      </svg>
    );
  }

  // Y-axis: clamp 0..1 so all sparklines share a comparable scale.
  // Different slugs have wildly different absolute drift levels; a
  // shared 0..1 axis means "tall line === high drift" reads correctly
  // when scanning the column top-down.
  const yMax = 1;
  const yMin = 0;
  const xStep = valid.length > 1 ? SPARKLINE_W / (valid.length - 1) : 0;

  const coords = valid.map((p, i) => {
    const x = i * xStep;
    const yRatio = (p.ratio - yMin) / (yMax - yMin);
    // SVG y-axis grows downward; invert so high drift draws toward the top.
    const y = SPARKLINE_H - yRatio * SPARKLINE_H;
    return [x, y] as const;
  });

  const pathD = coords.map(([x, y], i) => `${i === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  // `valid.length === 0` returns early above, so coords is non-empty.
  // The non-null assertion is the cheapest way to satisfy TS without
  // either re-asserting at runtime or pulling in noUncheckedIndexedAccess.
  const lastPoint = coords[coords.length - 1]!;
  const peak = Math.max(...valid.map((p) => p.ratio));
  const isHot = peak >= threshold;

  // Threshold y-coordinate (only drawn when threshold ∈ [yMin, yMax]).
  const thresholdY = SPARKLINE_H - ((threshold - yMin) / (yMax - yMin)) * SPARKLINE_H;

  // Tooltip: "<peak>% peak over <count> runs". Rendered via <title>
  // so keyboard users + screen readers also see it; CSS hover tooltip
  // libs are noisy here when 8+ rows render at once.
  const tooltip = `Peak ${Math.round(peak * 100)}% drift across ${valid.length} run(s)`;

  return (
    <svg width={SPARKLINE_W} height={SPARKLINE_H} aria-label={tooltip}>
      <title>{tooltip}</title>
      {/* Threshold line */}
      <line
        x1={0}
        y1={thresholdY}
        x2={SPARKLINE_W}
        y2={thresholdY}
        stroke="rgb(254 215 170)"
        strokeWidth={1}
        strokeDasharray="2 2"
      />
      {/* Drift line */}
      <path
        d={pathD}
        fill="none"
        stroke={isHot ? "rgb(180 83 9)" : "rgb(71 85 105)"}
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* End marker dot — emphasises "this is where we are now," which
          is the value ops actually want to act on. */}
      <circle
        cx={lastPoint[0]}
        cy={lastPoint[1]}
        r={2}
        fill={isHot ? "rgb(180 83 9)" : "rgb(71 85 105)"}
      />
    </svg>
  );
}
