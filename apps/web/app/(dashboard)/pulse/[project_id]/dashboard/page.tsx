"use client";
import { useParams } from "next/navigation";
import { ProjectDashboard, GanttChart } from "@aec/ui/pulse";
import { useProjectDashboard } from "../../../../../hooks/pulse";
import { useTasks } from "../../../../../hooks/pulse/useTasks";
import { PresenceBadge } from "@/components/PresenceBadge";

export default function PulseDashboardPage() {
  const params = useParams<{ project_id: string }>();
  const projectId = params.project_id;

  const dashboardQ = useProjectDashboard(projectId);
  const tasksQ = useTasks({ project_id: projectId, limit: 200 });

  if (dashboardQ.isLoading) return <p className="p-4">Loading…</p>;
  if (dashboardQ.error) {
    return (
      <p className="p-4 text-rose-600">Error: {dashboardQ.error.message}</p>
    );
  }
  if (!dashboardQ.data) return null;

  return (
    <div className="space-y-6">
      <div className="flex justify-end">
        <PresenceBadge resourceType="project" resourceId={projectId} />
      </div>
      <ProjectDashboard dashboard={dashboardQ.data} />
      <section>
        <h3 className="mb-2 text-sm font-semibold">Schedule (mini)</h3>
        <GanttChart tasks={tasksQ.data ?? []} />
      </section>
    </div>
  );
}
