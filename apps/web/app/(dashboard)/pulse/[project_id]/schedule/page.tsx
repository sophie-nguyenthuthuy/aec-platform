"use client";
import { useParams } from "next/navigation";
import { GanttChart } from "@aec/ui/pulse";
import { useTasks } from "../../../../../hooks/pulse/useTasks";

export default function PulseSchedulePage() {
  const params = useParams<{ project_id: string }>();
  const projectId = params.project_id;
  const tasksQ = useTasks({ project_id: projectId, limit: 500 });

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Schedule</h2>
      {tasksQ.isLoading ? (
        <p>Loading…</p>
      ) : (
        <GanttChart tasks={tasksQ.data ?? []} />
      )}
    </div>
  );
}
