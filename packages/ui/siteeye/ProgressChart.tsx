import type { ProgressSnapshot } from "./types";

interface Props {
  snapshots: ProgressSnapshot[];
  height?: number;
}

// Inline SVG sparkline so this package stays free of external chart deps.
export function ProgressChart({ snapshots, height = 180 }: Props) {
  if (snapshots.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-gray-200 p-6 text-center text-sm text-gray-500">
        No progress data yet.
      </div>
    );
  }

  const width = 720;
  const pad = 24;
  const max = 100;
  const n = snapshots.length;
  const xStep = n > 1 ? (width - 2 * pad) / (n - 1) : 0;

  const points = snapshots.map((s, i) => ({
    x: pad + i * xStep,
    y: pad + (height - 2 * pad) * (1 - Math.min(s.overall_progress_pct, max) / max),
    v: s.overall_progress_pct,
    d: s.snapshot_date,
  }));

  const path = points
    .map((p, i) => (i === 0 ? `M ${p.x} ${p.y}` : `L ${p.x} ${p.y}`))
    .join(" ");

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <svg viewBox={`0 0 ${width} ${height}`} className="h-auto w-full">
        <rect x={pad} y={pad} width={width - 2 * pad} height={height - 2 * pad} fill="#f9fafb" />
        <path d={path} fill="none" stroke="#0284c7" strokeWidth={2} />
        {points.map((p) => (
          <circle key={p.d} cx={p.x} cy={p.y} r={3} fill="#0284c7" />
        ))}
        {points.map((p, i) =>
          i === 0 || i === points.length - 1 ? (
            <text
              key={`lbl-${p.d}`}
              x={p.x}
              y={height - 6}
              textAnchor="middle"
              fontSize={10}
              fill="#6b7280"
            >
              {p.d}
            </text>
          ) : null,
        )}
      </svg>
    </div>
  );
}
