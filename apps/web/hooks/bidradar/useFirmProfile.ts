"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";
import type { FirmProfile, FirmProfileInput } from "@aec/ui/bidradar";
import { bidradarKeys } from "./keys";

export function useFirmProfile() {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: bidradarKeys.profile(),
    queryFn: async () => {
      const res = await apiFetch<FirmProfile | null>("/api/v1/bidradar/profile", {
        method: "GET",
        token,
        orgId,
      });
      return res.data ?? null;
    },
  });
}

export function useUpsertFirmProfile() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (input: FirmProfileInput) => {
      const res = await apiFetch<FirmProfile>("/api/v1/bidradar/profile", {
        method: "PUT",
        body: input,
        token,
        orgId,
      });
      return res.data!;
    },
    onSuccess: (data) => {
      qc.setQueryData(bidradarKeys.profile(), data);
      qc.invalidateQueries({ queryKey: bidradarKeys.all });
    },
  });
}
