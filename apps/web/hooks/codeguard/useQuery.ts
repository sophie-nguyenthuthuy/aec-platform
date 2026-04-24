"use client";

import { useMutation } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";
import type {
  QueryResponse,
  RegulationCategory,
} from "@aec/ui/codeguard";

export interface QueryRequest {
  project_id?: string;
  question: string;
  language?: "vi" | "en";
  jurisdiction?: string;
  categories?: RegulationCategory[];
  top_k?: number;
}

export function useCodeguardQuery() {
  const { token, orgId } = useSession();
  return useMutation({
    mutationKey: ["codeguard", "query"],
    mutationFn: async (payload: QueryRequest) => {
      const res = await apiFetch<QueryResponse>("/api/v1/codeguard/query", {
        method: "POST",
        token,
        orgId,
        body: payload,
      });
      return res.data as QueryResponse;
    },
  });
}
