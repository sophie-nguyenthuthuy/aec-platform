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
const invitationsKey = ["org", "invitations"] as const;

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

// ---------------- Invitations (token-based, real auth) ----------------
//
// The legacy `POST /org/members` directly inserts a `users` row with a
// random UUID — fine for seeding but broken for real auth, because the
// invitee's eventual Supabase JWT carries a different `sub` and the
// /me/orgs auto-provisioner would create a *second* users row that
// doesn't match the org_members FK.
//
// `useInviteMember` below issues a token-based invitation: the api
// returns an `accept_url` that the admin shares; the invitee opens it,
// sets their password, and the api creates a Supabase user whose UUID
// IS the local users.id.
export interface Invitation {
  id: UUID;
  email: string;
  role: Role;
  expires_at: ISODate;
  accepted_at: ISODate | null;
  invited_by: UUID | null;
  created_at: ISODate;
}

export interface InvitationCreated {
  id: UUID;
  organization_id: UUID;
  email: string;
  role: Role;
  token: UUID;
  expires_at: ISODate;
  accept_url: string;
}

export function useInviteMember() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (req: { email: string; role: Role }) => {
      const res = await apiFetch<InvitationCreated>(
        `/api/v1/orgs/${orgId}/invitations`,
        { method: "POST", token, orgId, body: req },
      );
      return res.data as InvitationCreated;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: invitationsKey }),
  });
}

export function usePendingInvitations() {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: invitationsKey,
    queryFn: async () => {
      const res = await apiFetch<Invitation[]>(
        `/api/v1/orgs/${orgId}/invitations`,
        { method: "GET", token, orgId },
      );
      // Hide accepted invitations from the list — once accepted they
      // appear in /org/members anyway and the row would just clutter UI.
      return (res.data ?? []).filter((i) => i.accepted_at === null) as Invitation[];
    },
  });
}

export function useRevokeInvitation() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (invitationId: UUID) => {
      await apiFetch<{ revoked: boolean }>(
        `/api/v1/orgs/${orgId}/invitations/${invitationId}`,
        { method: "DELETE", token, orgId },
      );
      return invitationId;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: invitationsKey }),
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
