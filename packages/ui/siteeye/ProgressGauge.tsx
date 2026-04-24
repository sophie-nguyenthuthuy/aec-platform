import type { ScheduleStatus } from "./types";

interface Props {
  value: number;
  label?: string;
  scheduleStatus?: ScheduleStatus;
  size?: number;
}

const STATUS_COLOR: Record<ScheduleStatus, string> = {
  on_track: "#16a34a",
  ahead: "#0ea5e9",
  behind: "#dc2626",
  unknown: "#6b7280",
};

export function ProgressGauge({
  value,
  label = "Overall progress",
  scheduleStatus = "unknown",
  size = 160,
}: Props) {
  const pct = Math.max(0, Math.min(100, value));
  const radius = (size - 16) / 2;
  const circumference = 2 * Math.PI * radius;
  const dash = (pct / 100) * circumference;
  const color = STATUS_COLOR[scheduleStatus];

  return (
    <div className="flex flex-col items-center gap-2">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="#e5e7eb"
          strokeWidth={12}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={12}
          strokeDasharray={`${dash} ${circumference - dash}`}
          strokeLinecap="round"
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
        <text
          x="50%"
          y="50%"
          dominantBaseline="middle"
          textAnchor="middle"
          fontSize={size * 0.2}
          fontWeight={600}
          fill="#111827"
        >
          {pct.toFixed(0)}%
        </text>
      </svg>
      <div className="text-sm text-gray-600">{label}</div>
      <div className="text-xs uppercase tracking-wide" style={{ color }}>
        {scheduleStatus.replace("_", " ")}
      </div>
    </div>
  );
}
