"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";
import type {
  RegulationCategory,
  ScanResponse,
} from "@aec/ui/codeguard";
import { codeguardKeys } from "./keys";

export interface ProjectParameters {
  project_type: string;
  use_class?: string;
  total_area_m2?: number;
  floors_above?: number;
  floors_below?: number;
  max_height_m?: number;
  occupancy?: number;
  location?: Record<string, unknown>;
  features?: Record<string, unknown>;
}

export interface ScanRequest {
  project_id: string;
  parameters: ProjectParameters;
  categories?: RegulationCategory[];
}

export interface ComplianceCheck {
  id: string;
  project_id: string | null;
  check_type: string;
  status: string;
  input: Record<string, unknown> | null;
  findings: unknown[] | null;
  regulations_referenced: string[];
  created_by: string | null;
  created_at: string;
}

export function useCodeguardScan() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationKey: ["codeguard", "scan"],
    mutationFn: async (payload: ScanRequest) => {
      const res = await apiFetch<ScanResponse>("/api/v1/codeguard/scan", {
        method: "POST",
        token,
        orgId,
        body: payload,
      });
      return res.data as ScanResponse;
    },
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: codeguardKeys.checks(vars.project_id) });
    },
  });
}

export function useProjectChecks(projectId: string | undefined, checkType?: string) {
  const { token, orgId } = useSession();
  return useQuery({
    enabled: Boolean(projectId),
    queryKey: projectId
      ? [...codeguardKeys.checks(projectId), checkType ?? "all"]
      : ["noop"],
    queryFn: async () => {
      const res = await apiFetch<ComplianceCheck[]>(
        `/api/v1/codeguard/checks/${projectId}`,
        {
          method: "GET",
          token,
          orgId,
          query: { check_type: checkType },
        },
      );
      return res.data as ComplianceCheck[];
    },
  });
}
