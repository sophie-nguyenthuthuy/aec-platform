import type { FC } from "react";

interface Props {
  score?: number | null;
  size?: "sm" | "md";
}

function scoreColor(score: number): string {
  if (score >= 75) return "bg-emerald-100 text-emerald-700 border-emerald-200";
  if (score >= 55) return "bg-amber-100 text-amber-700 border-amber-200";
  return "bg-slate-100 text-slate-600 border-slate-200";
}

export const MatchScoreBadge: FC<Props> = ({ score, size = "md" }) => {
  if (score == null) {
    return (
      <span className="inline-flex items-center rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-xs text-slate-500">
        —
      </span>
    );
  }
  const padding = size === "sm" ? "px-2 py-0.5 text-xs" : "px-2.5 py-1 text-sm";
  return (
    <span
      className={`inline-flex items-center rounded-full border font-medium ${padding} ${scoreColor(score)}`}
      aria-label={`Match score ${score.toFixed(0)}`}
    >
      {score.toFixed(0)}
    </span>
  );
};
