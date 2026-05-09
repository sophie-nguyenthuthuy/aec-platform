"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";


// Listing row — what the GET /api-keys endpoint returns. Notably:
//   * No `hash` (DB-only).
//   * No `key` (plaintext; only included on the create response).
// The frontend doesn't even define a field for them, which makes a
// regression where the backend leaks one immediately visible.
export interface ApiKeyRow {
  id: string;
  name: string;
  prefix: string;
  scopes: string[];
  rate_limit_per_minute: number | null;
  last_used_at: string | null;
  last_used_ip: string | null;
  revoked_at: string | null;
  expires_at: string | null;
  created_at: string;
  /**
   * "live" or "test". Backend always emits this; rows minted before
   * migration 0033 default to "live" via the column's server_default.
   */
  mode: "live" | "test";
  /**
   * Per-project allowlist. Empty array = "all projects" (back-compat
   * default for pre-0039 keys + new keys that don't opt into
   * per-project scoping). A non-empty array is a closed allowlist.
   */
  project_ids: string[];
}


// What the create endpoint returns — the listing shape PLUS the
// one-time plaintext key. Keep this distinct from `ApiKeyRow` so a
// listing component can't accidentally render `.key`.
export interface ApiKeyCreated extends ApiKeyRow {
  key: string;
}


export interface ApiKeyCreatePayload {
  name: string;
  scopes: string[];
  rate_limit_per_minute?: number | null;
  expires_at?: string | null;
  /**
   * "live" routes traffic to real org data; "test" routes to the
   * synthetic-data layer in `services.sandbox`. Server defaults to
   * "live" when omitted — same default as the backend's pydantic
   * model, so existing callers don't change behaviour.
   */
  mode?: "live" | "test";
  /**
   * Per-project allowlist. Omit OR pass `[]` for "all projects"
   * (the back-compat default). Pass a list of project UUIDs to
   * scope the key — `require_project_scope` on the backend then
   * 403s any request for a project outside this list.
   */
  project_ids?: string[];
}


export function useApiKeys() {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: ["api-keys"],
    queryFn: async () => {
      const res = await apiFetch<ApiKeyRow[]>("/api/v1/api-keys", {
        method: "GET",
        token,
        orgId,
      });
      return res.data as ApiKeyRow[];
    },
  });
}


export function useApiKeyScopes() {
  const { token, orgId } = useSession();
  // Scopes are static-ish — refetch on focus is overkill. Cache for
  // the session.
  return useQuery({
    queryKey: ["api-keys", "scopes"],
    staleTime: 1000 * 60 * 60, // 1h
    queryFn: async () => {
      const res = await apiFetch<string[]>("/api/v1/api-keys/scopes", {
        method: "GET",
        token,
        orgId,
      });
      return res.data as string[];
    },
  });
}


export function useCreateApiKey() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: ApiKeyCreatePayload) => {
      const res = await apiFetch<ApiKeyCreated>("/api/v1/api-keys", {
        method: "POST",
        token,
        orgId,
        body: payload,
      });
      return res.data as ApiKeyCreated;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["api-keys"] });
    },
  });
}


export function useRevokeApiKey() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      const res = await apiFetch<{ id: string; revoked_at: string }>(
        `/api/v1/api-keys/${id}/revoke`,
        { method: "POST", token, orgId },
      );
      return res.data as { id: string; revoked_at: string };
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["api-keys"] });
    },
  });
}


// ---------- Admin: cross-org usage telemetry ----------


export interface TopKeyRow {
  id: string;
  name: string;
  prefix: string;
  organization_id: string;
  revoked: boolean;
  total_count: number;
  error_count: number;
}


export interface ApiKeyUsageBucket {
  hour: string;
  success_count: number;
  error_count: number;
}


export interface ApiKeyUsage {
  total_count: number;
  error_count: number;
  error_rate: number;
  series: ApiKeyUsageBucket[];
}


export function useTopApiKeys(hours = 24, limit = 20) {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: ["api-keys", "top", hours, limit] as const,
    queryFn: async () => {
      const res = await apiFetch<TopKeyRow[]>("/api/v1/admin/api-keys/top", {
        method: "GET",
        token,
        orgId,
        query: { hours, limit },
      });
      return (res.data ?? []) as TopKeyRow[];
    },
  });
}


export function useApiKeyUsage(id: string, hours = 24) {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: ["api-keys", "usage", id, hours] as const,
    enabled: Boolean(id),
    queryFn: async () => {
      const res = await apiFetch<ApiKeyUsage>(
        `/api/v1/admin/api-keys/${id}/usage`,
        { method: "GET", token, orgId, query: { hours } },
      );
      return res.data as ApiKeyUsage;
    },
  });
}
