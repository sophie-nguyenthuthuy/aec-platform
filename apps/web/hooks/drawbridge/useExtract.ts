"use client";

import { useMutation } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";
import type { ExtractResponse } from "@aec/ui/drawbridge";

export interface ExtractInput {
  document_id: string;
  target?: "schedule" | "dimensions" | "materials" | "title_block" | "all";
  pages?: number[];
}

export function useExtract() {
  const { token, orgId } = useSession();
  return useMutation({
    mutationKey: ["drawbridge", "extract"],
    mutationFn: async (payload: ExtractInput) => {
      const res = await apiFetch<ExtractResponse>("/api/v1/drawbridge/extract", {
        method: "POST",
        token,
        orgId,
        body: { target: "schedule", ...payload },
      });
      return res.data as ExtractResponse;
    },
  });
}
