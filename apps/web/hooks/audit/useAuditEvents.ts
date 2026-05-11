"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";
import type { ISODate, UUID } from "@aec/types/envelope";


export interface AuditEvent {
  id: UUID;
  organization_id: UUID;
  actor_user_id: UUID | null;
  actor_api_key_id: UUID | null;
  // Populated only for human actors (actor_user_id non-null). For
  // api-key actors this is null and `actor_api_key_name` carries
  // the label instead. The UI uses the presence of one or the other
  // to pick rendering: avatar vs key icon.
  actor_email: string | null;
  // Populated only for api-key actors. Mutually exclusive with
  // `actor_email` — at most one is non-null on a given row.
  actor_api_key_name: string | null;
  action: string;
  resource_type: string;
  resource_id: UUID | null;
  before: Record<string, unknown>;
  after: Record<string, unknown>;
  ip: string | null;
  user_agent: string | null;
  created_at: ISODate;
}

export interface AuditFilters {
  resource_type?: string;
  resource_id?: UUID;
  action?: string;
  /** "user" / "api_key" / "system" — narrows the actor kind. */
  actor_kind?: "user" | "api_key" | "system";
  limit?: number;
  offset?: number;
}

export interface ProjectAuditFilters {
  action?: string;
  actor_kind?: "user" | "api_key" | "system";
  /** Limit results to events emitted in the last N days. */
  since_days?: number;
  limit?: number;
  offset?: number;
}

const auditKey = (filters: AuditFilters) =>
  ["audit", "events", filters] as const;

const projectAuditKey = (projectId: UUID, filters: ProjectAuditFilters) =>
  ["audit", "events", "project", projectId, filters] as const;

export function useAuditEvents(filters: AuditFilters = {}) {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: auditKey(filters),
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const res = await apiFetch<AuditEvent[]>("/api/v1/audit/events", {
        method: "GET",
        token,
        orgId,
        query: {
          resource_type: filters.resource_type,
          resource_id: filters.resource_id,
          action: filters.action,
          actor_kind: filters.actor_kind,
          limit: filters.limit ?? 50,
          offset: filters.offset ?? 0,
        },
      });
      return {
        data: (res.data ?? []) as AuditEvent[],
        meta: res.meta,
      };
    },
  });
}


// Project-scoped variant: queries the same `/api/v1/audit/events`
// endpoint but pre-attaches the `project_id` filter (which the
// backend treats as a resource-link narrowing across all relevant
// resource_types — change_orders, milestones, defects, etc.). Lets
// the per-project audit page stay thin: filter UI passes through
// here, the project_id stays out of the user-controlled filter
// surface.
export function useProjectAuditEvents(
  projectId: UUID,
  filters: ProjectAuditFilters = {},
) {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: projectAuditKey(projectId, filters),
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const res = await apiFetch<AuditEvent[]>("/api/v1/audit/events", {
        method: "GET",
        token,
        orgId,
        query: {
          project_id: projectId,
          action: filters.action,
          actor_kind: filters.actor_kind,
          since_days: filters.since_days,
          limit: filters.limit ?? 50,
          offset: filters.offset ?? 0,
        },
      });
      return {
        data: (res.data ?? []) as AuditEvent[],
        meta: res.meta,
      };
    },
  });
}
