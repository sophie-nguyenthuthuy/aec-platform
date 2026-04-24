"use client";
import { useMemo } from "react";
import type { Task, TaskStatus } from "@aec/types/pulse";
import { KanbanColumn } from "./KanbanColumn";
import { TaskCard } from "./TaskCard";

const ORDER: TaskStatus[] = ["todo", "in_progress", "review", "done", "blocked"];

export interface KanbanBoardProps {
  tasks: Task[];
  language?: "vi" | "en";
  onTaskClick?: (task: Task) => void;
  onStatusChange?: (taskId: string, toStatus: TaskStatus) => void;
}

export function KanbanBoard({
  tasks,
  language = "vi",
  onTaskClick,
  onStatusChange,
}: KanbanBoardProps) {
  const byStatus = useMemo(() => {
    const acc: Record<TaskStatus, Task[]> = {
      todo: [],
      in_progress: [],
      review: [],
      done: [],
      blocked: [],
    };
    for (const t of tasks) acc[t.status].push(t);
    for (const k of ORDER) {
      acc[k].sort((a, b) => (a.position ?? 0) - (b.position ?? 0));
    }
    return acc;
  }, [tasks]);

  return (
    <div className="flex gap-4 overflow-x-auto pb-2">
      {ORDER.map((status) => (
        <KanbanColumn
          key={status}
          status={status}
          tasks={byStatus[status]}
          language={language}
          onDropTask={onStatusChange}
        >
          {(task) => <TaskCard task={task} onClick={onTaskClick} draggable />}
        </KanbanColumn>
      ))}
    </div>
  );
}
