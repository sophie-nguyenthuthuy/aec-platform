"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";
import type { WeeklyDigest } from "@aec/ui/bidradar";
import { bidradarKeys } from "./keys";

export function useDigests() {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: bidradarKeys.digests(),
    queryFn: async () => {
      const res = await apiFetch<WeeklyDigest[]>("/api/v1/bidradar/digests", {
        method: "GET",
        token,
        orgId,
      });
      return res.data ?? [];
    },
  });
}

export function useSendDigest() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (args: { recipients: string[]; top_n?: number }) => {
      const res = await apiFetch<WeeklyDigest>("/api/v1/bidradar/digests/send", {
        method: "POST",
        body: { recipients: args.recipients, top_n: args.top_n ?? 5 },
        token,
        orgId,
      });
      return res.data!;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: bidradarKeys.digests() });
    },
  });
}
