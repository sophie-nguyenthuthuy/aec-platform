"use client";

import { useMutation } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";
import type { Discipline, QueryResponse } from "@aec/ui/drawbridge";

export interface DrawbridgeQueryInput {
  project_id: string;
  question: string;
  disciplines?: Discipline[];
  document_ids?: string[];
  top_k?: number;
  language?: "vi" | "en";
}

export function useDrawbridgeQuery() {
  const { token, orgId } = useSession();
  return useMutation({
    mutationKey: ["drawbridge", "query"],
    mutationFn: async (payload: DrawbridgeQueryInput) => {
      const res = await apiFetch<QueryResponse>("/api/v1/drawbridge/query", {
        method: "POST",
        token,
        orgId,
        body: payload,
      });
      return res.data as QueryResponse;
    },
  });
}
