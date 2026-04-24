"use client";
import { useState } from "react";
import { useParams } from "next/navigation";
import type { Task, TaskStatus } from "@aec/types/pulse";
import { KanbanBoard, TaskCard } from "@aec/ui/pulse";
import { Button } from "@aec/ui/primitives";
import {
  useBulkUpdateTasks,
  useTasks,
} from "../../../../../hooks/pulse/useTasks";

type View = "board" | "list";

export default function PulseTasksPage() {
  const params = useParams<{ project_id: string }>();
  const projectId = params.project_id;
  const [view, setView] = useState<View>("board");

  const tasksQ = useTasks({ project_id: projectId, limit: 200 });
  const bulkUpdate = useBulkUpdateTasks();

  const tasks = tasksQ.data ?? [];

  async function handleStatusChange(taskId: string, toStatus: TaskStatus) {
    await bulkUpdate.mutateAsync({ items: [{ id: taskId, status: toStatus }] });
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Tasks</h2>
        <div className="flex gap-2">
          <Button
            size="sm"
            variant={view === "board" ? "default" : "outline"}
            onClick={() => setView("board")}
          >
            Board
          </Button>
          <Button
            size="sm"
            variant={view === "list" ? "default" : "outline"}
            onClick={() => setView("list")}
          >
            List
          </Button>
        </div>
      </div>

      {tasksQ.isLoading && <p>Loading…</p>}
      {!tasksQ.isLoading && tasks.length === 0 && (
        <p className="text-muted-foreground">No tasks yet.</p>
      )}

      {view === "board" ? (
        <KanbanBoard
          tasks={tasks}
          onStatusChange={handleStatusChange}
        />
      ) : (
        <div className="grid gap-2 md:grid-cols-2 lg:grid-cols-3">
          {tasks.map((task: Task) => (
            <TaskCard key={task.id} task={task} />
          ))}
        </div>
      )}
    </div>
  );
}
