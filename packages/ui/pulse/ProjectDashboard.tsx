"use client";
import { AlertTriangle, CalendarCheck2, Coins, ListTodo } from "lucide-react";
import type { ProjectDashboard as Dashboard } from "@aec/types/pulse";
import { Card, CardContent, CardHeader, CardTitle } from "../primitives/card";
import { RAGStatus } from "./RAGStatus";

function fmtVND(v: number): string {
  return new Intl.NumberFormat("vi-VN", {
    style: "currency",
    currency: "VND",
    maximumFractionDigits: 0,
  }).format(v);
}

export interface ProjectDashboardProps {
  dashboard: Dashboard;
  language?: "vi" | "en";
}

export function ProjectDashboard({
  dashboard,
  language = "vi",
}: ProjectDashboardProps) {
  const totalTasks =
    dashboard.task_counts.todo +
    dashboard.task_counts.in_progress +
    dashboard.task_counts.review +
    dashboard.task_counts.done +
    dashboard.task_counts.blocked;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">
          {language === "vi" ? "Tổng quan dự án" : "Project overview"}
        </h2>
        <RAGStatus status={dashboard.rag_status} language={language} />
      </div>

      <div className="grid gap-4 md:grid-cols-4">
        <StatCard
          icon={<ListTodo className="h-4 w-4" />}
          label="Progress"
          value={`${dashboard.progress_pct.toFixed(0)}%`}
          sub={`${dashboard.task_counts.done}/${totalTasks} tasks done`}
        />
        <StatCard
          icon={<AlertTriangle className="h-4 w-4 text-rose-500" />}
          label="Overdue"
          value={String(dashboard.overdue_tasks)}
          sub={`${dashboard.task_counts.blocked} blocked`}
        />
        <StatCard
          icon={<Coins className="h-4 w-4 text-amber-500" />}
          label="Open change orders"
          value={String(dashboard.open_change_orders)}
          sub={fmtVND(dashboard.open_cost_impact_vnd)}
        />
        <StatCard
          icon={<CalendarCheck2 className="h-4 w-4 text-emerald-500" />}
          label="Upcoming milestones"
          value={String(dashboard.upcoming_milestones.length)}
          sub={
            dashboard.upcoming_milestones[0]
              ? `${dashboard.upcoming_milestones[0].name} — ${new Date(
                  dashboard.upcoming_milestones[0].due_date,
                ).toLocaleDateString()}`
              : "—"
          }
        />
      </div>

      {dashboard.alerts.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Alerts</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="list-disc pl-4 text-sm text-muted-foreground">
              {dashboard.alerts.map((a) => (
                <li key={a}>{a}</li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function StatCard({
  icon,
  label,
  value,
  sub,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  sub: string;
}) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          {icon}
          {label}
        </div>
        <div className="mt-1 text-2xl font-semibold">{value}</div>
        <div className="truncate text-xs text-muted-foreground">{sub}</div>
      </CardContent>
    </Card>
  );
}
