import type { Task } from "@aec/types/pulse";
import { cn } from "../lib/cn";

export interface GanttBarProps {
  task: Task;
  /** Earliest date shown on the chart, as a Date or ISO string */
  rangeStart: string | Date;
  /** Latest date shown on the chart */
  rangeEnd: string | Date;
  className?: string;
}

function toDate(v: string | Date): Date {
  return typeof v === "string" ? new Date(v) : v;
}

const phaseColor: Record<string, string> = {
  design: "bg-indigo-500",
  permit: "bg-amber-500",
  construction: "bg-emerald-500",
  closeout: "bg-slate-500",
};

export function GanttBar({ task, rangeStart, rangeEnd, className }: GanttBarProps) {
  const start = task.start_date ? toDate(task.start_date) : null;
  const end = task.due_date ? toDate(task.due_date) : null;
  if (!start || !end) return null;

  const rs = toDate(rangeStart).getTime();
  const re = toDate(rangeEnd).getTime();
  const span = Math.max(1, re - rs);
  const leftPct = Math.max(0, ((start.getTime() - rs) / span) * 100);
  const widthPct = Math.max(2, ((end.getTime() - start.getTime()) / span) * 100);

  return (
    <div
      className={cn("relative h-6 w-full rounded bg-muted", className)}
      aria-label={task.title}
      title={`${task.title} — ${start.toLocaleDateString()} → ${end.toLocaleDateString()}`}
    >
      <div
        className={cn(
          "absolute top-0 h-full rounded text-[10px] text-white",
          phaseColor[task.phase ?? ""] ?? "bg-primary",
          task.status === "done" && "opacity-70",
        )}
        style={{ left: `${leftPct}%`, width: `${widthPct}%` }}
      >
        <span className="truncate px-2 leading-6">{task.title}</span>
      </div>
    </div>
  );
}
