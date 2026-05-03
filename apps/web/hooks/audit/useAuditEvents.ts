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
  // For human actors this is `users.email`; for api-key actors it's
  // `api_key:<name>` (server-side COALESCE). NULL on cron / system rows.
  actor_email: string | null;
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
  limit?: number;
  offset?: number;
}

const auditKey = (filters: AuditFilters) =>
  ["audit", "events", filters] as const;

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
