"use client";

interface ComplianceScoreProps {
  pass: number;
  warn: number;
  fail: number;
  size?: number;
}

export function ComplianceScore({
  pass: passCount,
  warn,
  fail,
  size = 160,
}: ComplianceScoreProps): JSX.Element {
  const total = passCount + warn + fail;
  const radius = size / 2 - 14;
  const circumference = 2 * Math.PI * radius;
  const center = size / 2;

  const segments = total === 0
    ? [{ color: "#e2e8f0", length: circumference, offset: 0 }]
    : buildSegments({ pass: passCount, warn, fail, total, circumference });

  const scorePct = total === 0 ? 0 : Math.round((passCount / total) * 100);

  return (
    <div className="flex items-center gap-6">
      <svg width={size} height={size} className="shrink-0 -rotate-90">
        <circle
          cx={center}
          cy={center}
          r={radius}
          fill="none"
          stroke="#f1f5f9"
          strokeWidth={14}
        />
        {segments.map((seg, i) => (
          <circle
            key={i}
            cx={center}
            cy={center}
            r={radius}
            fill="none"
            stroke={seg.color}
            strokeWidth={14}
            strokeDasharray={`${seg.length} ${circumference}`}
            strokeDashoffset={-seg.offset}
          />
        ))}
        <text
          x={center}
          y={center}
          textAnchor="middle"
          dominantBaseline="central"
          className="fill-slate-900 text-2xl font-bold"
          transform={`rotate(90 ${center} ${center})`}
        >
          {scorePct}%
        </text>
      </svg>
      <div className="space-y-2 text-sm">
        <LegendRow color="#10b981" label="Đạt" value={passCount} />
        <LegendRow color="#f59e0b" label="Cảnh báo" value={warn} />
        <LegendRow color="#ef4444" label="Vi phạm" value={fail} />
      </div>
    </div>
  );
}

function buildSegments(args: {
  pass: number;
  warn: number;
  fail: number;
  total: number;
  circumference: number;
}): Array<{ color: string; length: number; offset: number }> {
  const { pass, warn, fail, total, circumference } = args;
  const parts = [
    { color: "#10b981", count: pass },
    { color: "#f59e0b", count: warn },
    { color: "#ef4444", count: fail },
  ];
  let offset = 0;
  const segments: Array<{ color: string; length: number; offset: number }> = [];
  for (const p of parts) {
    if (p.count === 0) continue;
    const length = (p.count / total) * circumference;
    segments.push({ color: p.color, length, offset });
    offset += length;
  }
  return segments;
}

function LegendRow({ color, label, value }: { color: string; label: string; value: number }): JSX.Element {
  return (
    <div className="flex items-center gap-2">
      <span className="h-3 w-3 rounded-sm" style={{ backgroundColor: color }} />
      <span className="text-slate-600">{label}</span>
      <span className="ml-auto font-semibold text-slate-900">{value}</span>
    </div>
  );
}
