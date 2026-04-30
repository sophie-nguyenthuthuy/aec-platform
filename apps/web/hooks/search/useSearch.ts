"use client";

import { useMutation } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";
import type { UUID } from "@aec/types/envelope";


export type SearchScope =
  | "documents"
  | "regulations"
  | "defects"
  | "rfis"
  | "proposals";


export interface SearchResult {
  scope: SearchScope;
  id: UUID;
  title: string;
  snippet: string | null;
  project_id: UUID | null;
  project_name: string | null;
  score: number;
  route: string | null;
  metadata: Record<string, unknown>;
}


export interface SearchResponse {
  query: string;
  total: number;
  results: SearchResult[];
}


export interface SearchRequest {
  query: string;
  scopes?: SearchScope[];
  project_id?: UUID;
  limit?: number;
}


/**
 * Cross-module search.
 *
 * Mutation (not query) because:
 *   * Each keystroke fires a fresh search; we WANT a manual `mutate()`
 *     trigger plus the keypress debouncing handled in the palette.
 *   * Results aren't naturally cached by query string — we'd risk
 *     stale hits when the user types fast.
 */
export function useSearch() {
  const { token, orgId } = useSession();
  return useMutation({
    mutationKey: ["search"],
    mutationFn: async (req: SearchRequest) => {
      const res = await apiFetch<SearchResponse>("/api/v1/search", {
        method: "POST",
        token,
        orgId,
        body: req,
      });
      return res.data as SearchResponse;
    },
  });
}
