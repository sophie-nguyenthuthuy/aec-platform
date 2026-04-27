"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";
import type { ISODate, UUID } from "@aec/types/envelope";


export type Role = "owner" | "admin" | "member" | "viewer";

export interface OrgMember {
  membership_id: UUID;
  user_id: UUID;
  email: string;
  full_name: string | null;
  avatar_url: string | null;
  role: Role;
  joined_at: ISODate;
}

const membersKey = ["org", "members"] as const;

export function useOrgMembers() {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: membersKey,
    queryFn: async () => {
      const res = await apiFetch<OrgMember[]>("/api/v1/org/members", {
        method: "GET",
        token,
        orgId,
      });
      return (res.data ?? []) as OrgMember[];
    },
  });
}

export function useInviteMember() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (req: { email: string; role: Role }) => {
      const res = await apiFetch<OrgMember>("/api/v1/org/members", {
        method: "POST",
        token,
        orgId,
        body: req,
      });
      return res.data as OrgMember;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: membersKey }),
  });
}

export function useUpdateMemberRole() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (req: { user_id: UUID; role: Role }) => {
      const res = await apiFetch<OrgMember>(
        `/api/v1/org/members/${req.user_id}`,
        { method: "PATCH", token, orgId, body: { role: req.role } },
      );
      return res.data as OrgMember;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: membersKey }),
  });
}

export function useRemoveMember() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (userId: UUID) => {
      await apiFetch<null>(`/api/v1/org/members/${userId}`, {
        method: "DELETE",
        token,
        orgId,
      });
      return userId;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: membersKey }),
  });
}
