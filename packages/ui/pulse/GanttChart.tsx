"use client";
import { useMemo } from "react";
import type { Task } from "@aec/types/pulse";
import { GanttBar } from "./GanttBar";

export interface GanttChartProps {
  tasks: Task[];
}

export function GanttChart({ tasks }: GanttChartProps) {
  const { rangeStart, rangeEnd, rows } = useMemo(() => {
    const rows = tasks.filter((t) => t.start_date && t.due_date);
    if (rows.length === 0) {
      const now = new Date();
      return { rangeStart: now, rangeEnd: now, rows };
    }
    const starts = rows.map((t) => new Date(t.start_date!).getTime());
    const ends = rows.map((t) => new Date(t.due_date!).getTime());
    return {
      rangeStart: new Date(Math.min(...starts)),
      rangeEnd: new Date(Math.max(...ends)),
      rows,
    };
  }, [tasks]);

  if (rows.length === 0) {
    return (
      <div className="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">
        No scheduled tasks.
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex justify-between text-xs text-muted-foreground">
        <span>{rangeStart.toLocaleDateString()}</span>
        <span>{rangeEnd.toLocaleDateString()}</span>
      </div>
      {rows.map((task) => (
        <GanttBar
          key={task.id}
          task={task}
          rangeStart={rangeStart}
          rangeEnd={rangeEnd}
        />
      ))}
    </div>
  );
}
