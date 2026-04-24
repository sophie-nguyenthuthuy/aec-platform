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
  ChangeOrder,
  ChangeOrderApproval,
  ChangeOrderCreate,
} from "@aec/types/pulse";
import { apiFetch } from "../../lib/api";
import { useSession } from "../../lib/auth-context";
import { pulseKeys, type CoListFilters } from "./keys";

export function useChangeOrders(
  filters: CoListFilters = {},
): UseQueryResult<ChangeOrder[]> {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: pulseKeys.changeOrders(filters),
    queryFn: async () => {
      const res = await apiFetch<ChangeOrder[]>("/api/v1/pulse/change-orders", {
        token,
        orgId,
        query: { ...filters },
      });
      return res.data ?? [];
    },
  });
}

export function useCreateChangeOrder(): UseMutationResult<
  ChangeOrder,
  Error,
  ChangeOrderCreate
> {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (input) => {
      const res = await apiFetch<ChangeOrder>("/api/v1/pulse/change-orders", {
        method: "POST",
        token,
        orgId,
        body: input,
      });
      if (!res.data) throw new Error("Create CO failed");
      return res.data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: pulseKeys.all });
    },
  });
}

export function useAnalyzeChangeOrder(): UseMutationResult<
  ChangeOrder,
  Error,
  UUID
> {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (coId) => {
      const res = await apiFetch<ChangeOrder>(
        `/api/v1/pulse/change-orders/${coId}/analyze`,
        { method: "POST", token, orgId, body: {} },
      );
      if (!res.data) throw new Error("Analyze CO failed");
      return res.data;
    },
    onSuccess: (co) => {
      qc.setQueryData(pulseKeys.changeOrder(co.id), co);
      qc.invalidateQueries({ queryKey: [...pulseKeys.all, "change-orders"] });
    },
  });
}

export function useApproveChangeOrder(): UseMutationResult<
  ChangeOrder,
  Error,
  { id: UUID; decision: ChangeOrderApproval }
> {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, decision }) => {
      const res = await apiFetch<ChangeOrder>(
        `/api/v1/pulse/change-orders/${id}/approve`,
        { method: "PATCH", token, orgId, body: decision },
      );
      if (!res.data) throw new Error("Approve CO failed");
      return res.data;
    },
    onSuccess: (co) => {
      qc.setQueryData(pulseKeys.changeOrder(co.id), co);
      qc.invalidateQueries({ queryKey: pulseKeys.all });
    },
  });
}
