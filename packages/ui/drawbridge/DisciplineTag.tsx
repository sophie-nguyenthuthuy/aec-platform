"use client";

import type { Discipline } from "./types";
import { cn } from "../lib/cn";

const STYLES: Record<Discipline, string> = {
  architectural: "bg-violet-100 text-violet-800 border-violet-200",
  structural: "bg-amber-100 text-amber-800 border-amber-200",
  mep: "bg-sky-100 text-sky-800 border-sky-200",
  civil: "bg-emerald-100 text-emerald-800 border-emerald-200",
};

const LABEL: Record<Discipline, string> = {
  architectural: "ARCH",
  structural: "STRUCT",
  mep: "MEP",
  civil: "CIVIL",
};

interface DisciplineTagProps {
  discipline: Discipline | null | undefined;
  className?: string;
  size?: "sm" | "md";
}

export function DisciplineTag({ discipline, className, size = "md" }: DisciplineTagProps): JSX.Element {
  if (!discipline) {
    return (
      <span
        className={cn(
          "inline-flex items-center rounded border bg-slate-100 text-slate-600 border-slate-200 font-medium",
          size === "sm" ? "px-1.5 py-0 text-[10px]" : "px-2 py-0.5 text-xs",
          className,
        )}
      >
        —
      </span>
    );
  }
  return (
    <span
      className={cn(
        "inline-flex items-center rounded border font-semibold uppercase tracking-wide",
        STYLES[discipline],
        size === "sm" ? "px-1.5 py-0 text-[10px]" : "px-2 py-0.5 text-xs",
        className,
      )}
    >
      {LABEL[discipline]}
    </span>
  );
}
