"use client";

import type { EstimateConfidence } from "@aec/types";

import { cn } from "../lib/cn";

interface ConfidenceMeterProps {
  confidence: EstimateConfidence | null;
  className?: string;
}

const LEVELS: { key: EstimateConfidence; label: string; accuracy: string; color: string }[] = [
  { key: "rough_order", label: "Rough order", accuracy: "±30%", color: "bg-amber-400" },
  { key: "preliminary", label: "Preliminary", accuracy: "±15%", color: "bg-sky-500" },
  { key: "detailed", label: "Detailed", accuracy: "±5%", color: "bg-emerald-500" },
];

export function ConfidenceMeter({ confidence, className }: ConfidenceMeterProps): JSX.Element {
  const activeIdx = confidence ? LEVELS.findIndex((l) => l.key === confidence) : -1;
  const active = activeIdx >= 0 ? LEVELS[activeIdx] : null;

  return (
    <div className={cn("flex flex-col gap-2", className)}>
      <div className="flex items-center justify-between text-xs font-medium text-slate-600">
        <span>Estimate confidence</span>
        {active ? (
          <span className="text-slate-900">
            {active.label} · {active.accuracy}
          </span>
        ) : (
          <span className="text-slate-400">—</span>
        )}
      </div>
      <div className="flex gap-1">
        {LEVELS.map((level, i) => (
          <div
            key={level.key}
            className={cn(
              "h-2 flex-1 rounded-full transition-colors",
              i <= activeIdx ? level.color : "bg-slate-200",
            )}
            title={`${level.label} · ${level.accuracy}`}
          />
        ))}
      </div>
    </div>
  );
}
