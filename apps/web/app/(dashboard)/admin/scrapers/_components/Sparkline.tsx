/**
 * Inline SVG drift sparkline for the `/admin/scrapers` summary table.
 *
 * Extracted into its own module so vitest can exercise the gap /
 * threshold / empty-state branches without mounting the whole page
 * (which depends on `useSession`, `useTranslations`, and a TanStack
 * Query client). The page imports `<Sparkline>` from here.
 *
 * Design choices and rationale live with the implementation below;
 * the short version: raw SVG over a chart lib because per-row
 * wrapper cost dominates at 8+ rows, and a 14–30 point series
 * doesn't need axes/tooltips/animation.
 */

import type { ScraperRunsSummaryPoint } from "@/hooks/admin";


export const SPARKLINE_W = 80;
export const SPARKLINE_H = 22;


export function Sparkline({
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
      <svg width={SPARKLINE_W} height={SPARKLINE_H} aria-hidden="true" data-testid="sparkline-empty">
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
  const lineColor = isHot ? "rgb(180 83 9)" : "rgb(71 85 105)";

  // Threshold y-coordinate (only drawn when threshold ∈ [yMin, yMax]).
  const thresholdY = SPARKLINE_H - ((threshold - yMin) / (yMax - yMin)) * SPARKLINE_H;

  // Tooltip: "<peak>% peak over <count> runs". Rendered via <title>
  // so keyboard users + screen readers also see it; CSS hover tooltip
  // libs are noisy here when 8+ rows render at once.
  const tooltip = `Peak ${Math.round(peak * 100)}% drift across ${valid.length} run(s)`;

  return (
    <svg width={SPARKLINE_W} height={SPARKLINE_H} aria-label={tooltip} data-testid="sparkline">
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
        data-testid="sparkline-threshold"
      />
      {/* Drift line */}
      <path
        d={pathD}
        fill="none"
        stroke={lineColor}
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
        data-testid="sparkline-path"
      />
      {/* End marker dot — emphasises "this is where we are now," which
          is the value ops actually want to act on. */}
      <circle
        cx={lastPoint[0]}
        cy={lastPoint[1]}
        r={2}
        fill={lineColor}
        data-testid="sparkline-end-dot"
      />
    </svg>
  );
}
