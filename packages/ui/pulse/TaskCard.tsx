"use client";
import { CalendarDays, Flag, User } from "lucide-react";
import type { Task } from "@aec/types/pulse";
import { Card } from "../primitives/card";
import { Badge } from "../primitives/badge";
import { cn } from "../lib/cn";

const priorityTone: Record<Task["priority"], string> = {
  low: "text-slate-500",
  normal: "text-slate-600",
  high: "text-amber-600",
  urgent: "text-rose-600",
};

export interface TaskCardProps {
  task: Task;
  onClick?: (task: Task) => void;
  draggable?: boolean;
  onDragStart?: (task: Task) => void;
}

export function TaskCard({ task, onClick, draggable, onDragStart }: TaskCardProps) {
  const overdue =
    task.due_date &&
    task.status !== "done" &&
    new Date(task.due_date) < new Date();

  return (
    <Card
      role="button"
      tabIndex={0}
      draggable={draggable}
      onDragStart={() => onDragStart?.(task)}
      onClick={() => onClick?.(task)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") onClick?.(task);
      }}
      className="cursor-pointer p-3 text-sm shadow-none transition hover:border-primary/40"
    >
      <div className="flex items-start justify-between gap-2">
        <span className="line-clamp-2 font-medium">{task.title}</span>
        <Flag
          className={cn("mt-0.5 h-4 w-4 shrink-0", priorityTone[task.priority])}
          aria-label={`priority ${task.priority}`}
        />
      </div>

      {task.description && (
        <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
          {task.description}
        </p>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        {task.assignee_id && (
          <span className="inline-flex items-center gap-1">
            <User className="h-3 w-3" />
            {task.assignee_id.slice(0, 6)}
          </span>
        )}
        {task.due_date && (
          <span
            className={cn(
              "inline-flex items-center gap-1",
              overdue && "text-rose-600",
            )}
          >
            <CalendarDays className="h-3 w-3" />
            {new Date(task.due_date).toLocaleDateString("vi-VN")}
          </span>
        )}
        {task.tags?.slice(0, 2).map((tag) => (
          <Badge key={tag} variant="secondary" className="text-[10px]">
            {tag}
          </Badge>
        ))}
      </div>
    </Card>
  );
}
