import type { UUID } from "@aec/types/envelope";
import type { Phase, TaskStatus, ChangeOrderStatus } from "@aec/types/pulse";

export const pulseKeys = {
  all: ["pulse"] as const,
  dashboards: () => [...pulseKeys.all, "dashboards"] as const,
  dashboard: (projectId: UUID) => [...pulseKeys.dashboards(), projectId] as const,
  tasks: (filters?: TaskListFilters) =>
    [...pulseKeys.all, "tasks", filters ?? {}] as const,
  task: (id: UUID) => [...pulseKeys.all, "task", id] as const,
  changeOrders: (filters?: CoListFilters) =>
    [...pulseKeys.all, "change-orders", filters ?? {}] as const,
  changeOrder: (id: UUID) => [...pulseKeys.all, "change-order", id] as const,
  meetingNotes: (projectId?: UUID) =>
    [...pulseKeys.all, "meeting-notes", projectId ?? null] as const,
  reports: (projectId?: UUID) =>
    [...pulseKeys.all, "reports", projectId ?? null] as const,
};

export interface TaskListFilters {
  project_id?: UUID;
  assignee_id?: UUID;
  phase?: Phase;
  status?: TaskStatus;
  parent_id?: UUID;
  limit?: number;
  offset?: number;
}

export interface CoListFilters {
  project_id?: UUID;
  status?: ChangeOrderStatus;
  limit?: number;
  offset?: number;
}
