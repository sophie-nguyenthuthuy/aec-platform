"use client";

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";
import type { ISODate, UUID } from "@aec/types/envelope";


export interface WebhookSubscription {
  id: UUID;
  url: string;
  event_types: string[];
  enabled: boolean;
  last_delivery_at: ISODate | null;
  failure_count: number;
  created_at: ISODate;
  /** Cycle P1 — rotation grace status. True iff the subscription is
   *  currently in the 24h post-rotation grace window AND the
   *  dispatcher is emitting `X-AEC-Signature-Previous` alongside the
   *  primary signature. Computed server-side from
   *  `secret_previous_expires_at`; never persists. False on a
   *  subscription that has never rotated. */
  secret_previous_active: boolean;
  /** Seconds remaining until the rotation grace expires. 0 when not
   *  in a grace. Frontend formats as "Xh left" / "Xm left" depending
   *  on magnitude. */
  secret_previous_grace_seconds_remaining: number;
}

export interface WebhookCreated extends WebhookSubscription {
  /** Returned ONCE on creation. The list endpoint never includes this. */
  secret: string;
}

export interface WebhookDelivery {
  id: UUID;
  // The subscription this delivery belongs to. Per-subscription
  // listings already have it in the URL — but the dead-letter
  // dashboard shows failures across every subscription, so each row
  // needs to link back somewhere.
  subscription_id: UUID;
  event_type: string;
  status: "pending" | "in_flight" | "delivered" | "failed";
  attempt_count: number;
  response_status: number | null;
  response_body_snippet: string | null;
  error_message: string | null;
  delivered_at: ISODate | null;
  created_at: ISODate;
  payload: Record<string, unknown>;
}

export interface CreateWebhookRequest {
  url: string;
  event_types: string[];
}

export interface UpdateWebhookRequest {
  enabled?: boolean;
  event_types?: string[];
}


const KEY = {
  list: ["webhooks", "list"] as const,
  deliveries: (id: UUID) => ["webhooks", "deliveries", id] as const,
};


export function useWebhooks(): UseQueryResult<WebhookSubscription[]> {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: KEY.list,
    queryFn: async () => {
      const res = await apiFetch<WebhookSubscription[]>("/api/v1/webhooks", {
        method: "GET",
        token,
        orgId,
      });
      return (res.data ?? []) as WebhookSubscription[];
    },
  });
}


export function useCreateWebhook(): UseMutationResult<
  WebhookCreated,
  Error,
  CreateWebhookRequest
> {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (req) => {
      const res = await apiFetch<WebhookCreated>("/api/v1/webhooks", {
        method: "POST",
        token,
        orgId,
        body: req,
      });
      return res.data as WebhookCreated;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY.list }),
  });
}


export function useUpdateWebhook(
  id: UUID,
): UseMutationResult<WebhookSubscription, Error, UpdateWebhookRequest> {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (req) => {
      const res = await apiFetch<WebhookSubscription>(`/api/v1/webhooks/${id}`, {
        method: "PATCH",
        token,
        orgId,
        body: req,
      });
      return res.data as WebhookSubscription;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEY.list });
      qc.invalidateQueries({ queryKey: KEY.deliveries(id) });
    },
  });
}


export function useDeleteWebhook(): UseMutationResult<null, Error, UUID> {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id) => {
      await apiFetch<null>(`/api/v1/webhooks/${id}`, {
        method: "DELETE",
        token,
        orgId,
      });
      return null;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY.list }),
  });
}


export function useTestWebhook(): UseMutationResult<
  { queued: number; subscription_id: UUID },
  Error,
  UUID
> {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id) => {
      const res = await apiFetch<{ queued: number; subscription_id: UUID }>(
        `/api/v1/webhooks/${id}/test`,
        { method: "POST", token, orgId },
      );
      return res.data as { queued: number; subscription_id: UUID };
    },
    onSuccess: (_data, id) => {
      // The dispatch happens asynchronously on the cron tick — refetch
      // recent deliveries 1.5s later so the user sees the test fire.
      setTimeout(() => {
        qc.invalidateQueries({ queryKey: KEY.deliveries(id) });
      }, 1500);
    },
  });
}


export interface DeliveriesFilters {
  status?: "pending" | "delivered" | "failed";
  since_days?: number;
  limit?: number;
}


export function useWebhookDeliveries(
  id: UUID,
  filters: DeliveriesFilters = {},
): UseQueryResult<WebhookDelivery[]> {
  const { token, orgId } = useSession();
  return useQuery({
    // The filters are part of the cache key so toggling status doesn't
    // serve stale results from a different filter set.
    queryKey: [...KEY.deliveries(id), filters] as const,
    queryFn: async () => {
      const res = await apiFetch<WebhookDelivery[]>(
        `/api/v1/webhooks/${id}/deliveries`,
        {
          method: "GET",
          token,
          orgId,
          query: {
            status: filters.status,
            since_days: filters.since_days ?? 7,
            limit: filters.limit ?? 50,
          },
        },
      );
      return (res.data ?? []) as WebhookDelivery[];
    },
    enabled: Boolean(id),
  });
}


export interface DeliveriesHistogramBucket {
  day: string;
  delivered: number;
  failed: number;
  pending: number;
}


/**
 * Day-bucketed delivery counts. Drives the small histogram on the
 * webhook detail page — failure spikes jump out visually before the
 * customer reports the breakage.
 */
export function useDeliveriesHistogram(
  id: UUID,
  days = 7,
): UseQueryResult<DeliveriesHistogramBucket[]> {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: ["webhooks", "histogram", id, days] as const,
    queryFn: async () => {
      const res = await apiFetch<DeliveriesHistogramBucket[]>(
        `/api/v1/webhooks/${id}/deliveries/histogram`,
        { method: "GET", token, orgId, query: { days } },
      );
      return (res.data ?? []) as DeliveriesHistogramBucket[];
    },
    enabled: Boolean(id),
  });
}


/**
 * Re-fire a failed (or any) delivery. Inserts a fresh `pending` row
 * with a NEW id (which doubles as the receiver's idempotency key).
 * The dispatch cron picks it up on the next tick.
 */
export function useRedeliverWebhook(
  subscriptionId: UUID,
): UseMutationResult<{ id: UUID; subscription_id: UUID }, Error, UUID> {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (deliveryId) => {
      const res = await apiFetch<{ id: UUID; subscription_id: UUID }>(
        `/api/v1/webhooks/deliveries/${deliveryId}/redeliver`,
        { method: "POST", token, orgId },
      );
      return res.data as { id: UUID; subscription_id: UUID };
    },
    onSuccess: () => {
      // Wait for the cron tick before refetching — the delivery is
      // pending until the worker picks it up.
      setTimeout(() => {
        qc.invalidateQueries({ queryKey: KEY.deliveries(subscriptionId) });
        qc.invalidateQueries({ queryKey: ["webhooks", "histogram", subscriptionId] });
      }, 1500);
    },
  });
}


// ---------- Secret rotation ----------


export interface RotateSecretResponse {
  id: UUID;
  /** The NEW secret, returned exactly once. The list endpoint never echoes it. */
  secret: string;
  grace_seconds: number;
  note: string;
}


/**
 * Rotate a webhook subscription's HMAC secret. Returns the NEW secret
 * exactly once (same one-shot disclosure shape as creation).
 *
 * The previous secret keeps verifying on the receiver side for a 24h
 * grace window — see `services.webhooks.rotate_secret` and the
 * dispatcher's dual-signature emit (`X-AEC-Signature` +
 * `X-AEC-Signature-Previous`). Customers should:
 *
 *   1. Click rotate → capture the new secret from the response.
 *   2. Deploy receiver config with the NEW secret.
 *   3. Smoke-test deliveries.
 *   4. Within 24h, retire the old secret on the receiver side.
 */
export function useRotateWebhookSecret(): UseMutationResult<
  RotateSecretResponse,
  Error,
  UUID
> {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id) => {
      const res = await apiFetch<RotateSecretResponse>(
        `/api/v1/webhooks/${id}/rotate-secret`,
        { method: "POST", token, orgId },
      );
      return res.data as RotateSecretResponse;
    },
    onSuccess: () => {
      // The list view doesn't show the secret but it does show
      // last_delivery_at — invalidate so any subsequent delivery
      // refetches reflect the rotation event.
      qc.invalidateQueries({ queryKey: KEY.list });
    },
  });
}


// ---------- Dead-letter dashboard ----------


export interface DeadLetterFilters {
  since_days?: number;
  limit?: number;
}


const DEAD_LETTER_KEY = ["webhooks", "dead-letter"] as const;


export function useDeadLetterDeliveries(
  filters: DeadLetterFilters = {},
): UseQueryResult<WebhookDelivery[]> {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: [...DEAD_LETTER_KEY, filters] as const,
    queryFn: async () => {
      const res = await apiFetch<WebhookDelivery[]>(
        "/api/v1/webhooks/deliveries/dead-letter",
        {
          method: "GET",
          token,
          orgId,
          query: {
            since_days: filters.since_days ?? 7,
            limit: filters.limit ?? 100,
          },
        },
      );
      return (res.data ?? []) as WebhookDelivery[];
    },
  });
}


export function useRedeliverFromDeadLetter(): UseMutationResult<
  { id: UUID; subscription_id: UUID },
  Error,
  UUID
> {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (deliveryId) => {
      const res = await apiFetch<{ id: UUID; subscription_id: UUID }>(
        `/api/v1/webhooks/deliveries/${deliveryId}/redeliver`,
        { method: "POST", token, orgId },
      );
      return res.data as { id: UUID; subscription_id: UUID };
    },
    onSuccess: (data) => {
      setTimeout(() => {
        qc.invalidateQueries({ queryKey: DEAD_LETTER_KEY });
        qc.invalidateQueries({ queryKey: KEY.deliveries(data.subscription_id) });
      }, 1500);
    },
  });
}
