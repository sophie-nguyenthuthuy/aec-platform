"use client";
import {
  useMutation,
  useQueryClient,
  type UseMutationResult,
} from "@tanstack/react-query";
import type { UUID } from "@aec/types/envelope";
import type {
  ClientReport,
  ReportGenerateRequest,
  ReportSendRequest,
} from "@aec/types/pulse";
import { apiFetch } from "../../lib/api";
import { useSession } from "../../lib/auth-context";
import { pulseKeys } from "./keys";

export function useGenerateReport(): UseMutationResult<
  ClientReport,
  Error,
  ReportGenerateRequest
> {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (input) => {
      const res = await apiFetch<ClientReport>(
        "/api/v1/pulse/client-reports/generate",
        { method: "POST", token, orgId, body: input },
      );
      if (!res.data) throw new Error("Generate report failed");
      return res.data;
    },
    onSuccess: (report) => {
      qc.invalidateQueries({ queryKey: pulseKeys.reports(report.project_id) });
    },
  });
}

export function useSendReport(): UseMutationResult<
  ClientReport,
  Error,
  { id: UUID; payload: ReportSendRequest }
> {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, payload }) => {
      const res = await apiFetch<ClientReport>(
        `/api/v1/pulse/client-reports/${id}/send`,
        { method: "POST", token, orgId, body: payload },
      );
      if (!res.data) throw new Error("Send report failed");
      return res.data;
    },
    onSuccess: (report) => {
      qc.invalidateQueries({ queryKey: pulseKeys.reports(report.project_id) });
    },
  });
}
