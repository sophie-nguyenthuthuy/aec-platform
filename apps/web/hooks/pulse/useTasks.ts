"use client";
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";
import type { UUID } from "@aec/types/envelope";
import type {
  Task,
  TaskBulkUpdate,
  TaskCreate,
  TaskUpdate,
} from "@aec/types/pulse";
import { apiFetch } from "../../lib/api";
import { useSession } from "../../lib/auth-context";
import { pulseKeys, type TaskListFilters } from "./keys";

export function useTasks(
  filters: TaskListFilters = {},
): UseQueryResult<Task[]> {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: pulseKeys.tasks(filters),
    queryFn: async () => {
      const res = await apiFetch<Task[]>("/api/v1/pulse/tasks", {
        token,
        orgId,
        query: { ...filters },
      });
      return res.data ?? [];
    },
  });
}

export function useCreateTask(): UseMutationResult<Task, Error, TaskCreate> {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (input) => {
      const res = await apiFetch<Task>("/api/v1/pulse/tasks", {
        method: "POST",
        token,
        orgId,
        body: input,
      });
      if (!res.data) throw new Error("Create task failed");
      return res.data;
    },
    onSuccess: (_task, vars) => {
      qc.invalidateQueries({ queryKey: pulseKeys.all });
      qc.invalidateQueries({
        queryKey: pulseKeys.dashboard(vars.project_id),
      });
    },
  });
}

export function useUpdateTask(): UseMutationResult<
  Task,
  Error,
  { id: UUID; patch: TaskUpdate }
> {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, patch }) => {
      const res = await apiFetch<Task>(`/api/v1/pulse/tasks/${id}`, {
        method: "PATCH",
        token,
        orgId,
        body: patch,
      });
      if (!res.data) throw new Error("Update task failed");
      return res.data;
    },
    onSuccess: (task) => {
      qc.invalidateQueries({ queryKey: pulseKeys.all });
      qc.setQueryData(pulseKeys.task(task.id), task);
    },
  });
}

export function useBulkUpdateTasks(): UseMutationResult<
  Task[],
  Error,
  TaskBulkUpdate
> {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (input) => {
      const res = await apiFetch<Task[]>("/api/v1/pulse/tasks/bulk", {
        method: "POST",
        token,
        orgId,
        body: input,
      });
      return res.data ?? [];
    },
    onMutate: async (input) => {
      await qc.cancelQueries({ queryKey: [...pulseKeys.all, "tasks"] });
      const previous = qc.getQueriesData<Task[]>({
        queryKey: [...pulseKeys.all, "tasks"],
      });
      const byId = new Map(input.items.map((i) => [i.id, i]));
      for (const [key, tasks] of previous) {
        if (!tasks) continue;
        qc.setQueryData<Task[]>(
          key,
          tasks.map((t) => {
            const patch = byId.get(t.id);
            if (!patch) return t;
            return {
              ...t,
              ...(patch.status !== undefined ? { status: patch.status } : {}),
              ...(patch.phase !== undefined ? { phase: patch.phase } : {}),
              ...(patch.position !== undefined
                ? { position: patch.position }
                : {}),
              ...(patch.assignee_id !== undefined
                ? { assignee_id: patch.assignee_id }
                : {}),
            };
          }),
        );
      }
      return { previous };
    },
    onError: (_err, _vars, ctx) => {
      if (!ctx) return;
      for (const [key, tasks] of ctx.previous) {
        qc.setQueryData(key, tasks);
      }
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: pulseKeys.all });
    },
  });
}
