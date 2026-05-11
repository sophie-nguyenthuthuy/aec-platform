/**
 * Tiny SVG sparkline for API-key call volume.
 *
 * Distinct from `app/(dashboard)/admin/scrapers/_components/Sparkline.tsx`
 * — that one renders a 0..1 ratio with a threshold line; this one
 * renders absolute call counts (success vs error stacked) with no
 * threshold concept. Different shape, different file.
 *
 * Raw SVG over a chart lib because the table has 5–50 rows and a
 * per-row chart wrapper component dominates initial render. 24 hour
 * buckets is also small enough that no axes/tooltips are needed.
 */

import type { ApiKeyUsageBucket } from "@/hooks/apiKeys";


const W = 80;
const H = 22;


export function UsageSparkline({
  buckets,
}: {
  buckets: ApiKeyUsageBucket[];
}): React.ReactElement {
  if (buckets.length === 0) {
    // No telemetry → flat dim baseline so the column keeps its
    // alignment; matches the scrapers Sparkline empty-state idiom.
    return (
      <svg width={W} height={H} aria-hidden="true">
        <line
          x1={0}
          y1={H / 2}
          x2={W}
          y2={H / 2}
          stroke="rgb(203 213 225)"
          strokeWidth={1}
          strokeDasharray="2 2"
        />
      </svg>
    );
  }

  // Y-axis: total calls per bucket. Scale to the busiest bucket so a
  // 5-call key reads as "tall" and a 50k-call key reads as "tall" too —
  // we're showing shape over time, not absolute volume (the totals
  // tile shows that separately).
  const totals = buckets.map((b) => b.success_count + b.error_count);
  const yMax = Math.max(...totals, 1);
  const xStep = buckets.length > 1 ? W / (buckets.length - 1) : 0;

  const errCoords = buckets.map((b, i) => {
    const x = i * xStep;
    const yRatio = b.error_count / yMax;
    const y = H - yRatio * H;
    return [x, y] as const;
  });
  const totalCoords = buckets.map((b, i) => {
    const x = i * xStep;
    const yRatio = (b.success_count + b.error_count) / yMax;
    const y = H - yRatio * H;
    return [x, y] as const;
  });

  const totalPath = totalCoords
    .map(([x, y], i) => `${i === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`)
    .join(" ");
  const errorPath = errCoords
    .map(([x, y], i) => `${i === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`)
    .join(" ");
  const last = totalCoords[totalCoords.length - 1]!;

  const totalSum = totals.reduce((a, b) => a + b, 0);
  const errorSum = buckets.reduce((a, b) => a + b.error_count, 0);
  const tooltip = `${totalSum} call(s) over ${buckets.length} hour(s), ${errorSum} error(s)`;

  return (
    <svg width={W} height={H} aria-label={tooltip}>
      <title>{tooltip}</title>
      {/* Total volume line — slate, the dominant signal. */}
      <path
        d={totalPath}
        fill="none"
        stroke="rgb(71 85 105)"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* Error overlay — rose. Drawn on top so a spike is visible
          even when total is high. */}
      <path
        d={errorPath}
        fill="none"
        stroke="rgb(225 29 72)"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx={last[0]} cy={last[1]} r={2} fill="rgb(71 85 105)" />
    </svg>
  );
}
