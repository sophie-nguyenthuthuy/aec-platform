import type { FC } from "react";
import type { CompetitionLevel } from "./types";

interface Props {
  level?: CompetitionLevel | string | null;
}

const LABELS: Record<string, string> = {
  low: "Low",
  moderate: "Moderate",
  high: "High",
  very_high: "Very high",
};

const STYLES: Record<string, string> = {
  low: "bg-emerald-50 text-emerald-700 border-emerald-200",
  moderate: "bg-sky-50 text-sky-700 border-sky-200",
  high: "bg-amber-50 text-amber-700 border-amber-200",
  very_high: "bg-rose-50 text-rose-700 border-rose-200",
};

export const CompetitionBadge: FC<Props> = ({ level }) => {
  if (!level) return null;
  return (
    <span
      className={`inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium ${
        STYLES[level] ?? "bg-slate-50 text-slate-600 border-slate-200"
      }`}
    >
      {LABELS[level] ?? level}
    </span>
  );
};
