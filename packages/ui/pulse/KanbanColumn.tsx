"use client";
import { useState, type ReactNode } from "react";
import type { Task, TaskStatus } from "@aec/types/pulse";
import { cn } from "../lib/cn";

const labelVi: Record<TaskStatus, string> = {
  todo: "Chưa bắt đầu",
  in_progress: "Đang làm",
  review: "Rà soát",
  done: "Hoàn thành",
  blocked: "Bị chặn",
};

const columnTone: Record<TaskStatus, string> = {
  todo: "bg-slate-50",
  in_progress: "bg-blue-50",
  review: "bg-indigo-50",
  done: "bg-emerald-50",
  blocked: "bg-rose-50",
};

export interface KanbanColumnProps {
  status: TaskStatus;
  tasks: Task[];
  language?: "vi" | "en";
  onDropTask?: (taskId: string, toStatus: TaskStatus) => void;
  children: (task: Task) => ReactNode;
}

export function KanbanColumn({
  status,
  tasks,
  language = "vi",
  onDropTask,
  children,
}: KanbanColumnProps) {
  const [isOver, setIsOver] = useState(false);
  const title = language === "en" ? status.replace("_", " ") : labelVi[status];

  return (
    <section
      className={cn(
        "flex min-h-[320px] w-72 shrink-0 flex-col rounded-lg border",
        columnTone[status],
        isOver && "ring-2 ring-primary",
      )}
      onDragOver={(e) => {
        e.preventDefault();
        setIsOver(true);
      }}
      onDragLeave={() => setIsOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setIsOver(false);
        const taskId = e.dataTransfer.getData("text/task-id");
        if (taskId && onDropTask) onDropTask(taskId, status);
      }}
      aria-label={title}
    >
      <header className="flex items-center justify-between border-b px-3 py-2">
        <h3 className="text-sm font-semibold capitalize">{title}</h3>
        <span className="text-xs text-muted-foreground">{tasks.length}</span>
      </header>
      <div className="flex flex-col gap-2 p-2">
        {tasks.map((task) => (
          <div
            key={task.id}
            draggable
            onDragStart={(e) => e.dataTransfer.setData("text/task-id", task.id)}
          >
            {children(task)}
          </div>
        ))}
      </div>
    </section>
  );
}
