"use client";

/**
 * React Query hooks for the platform-admin `/admin/webhook-deliveries`
 * dashboard.
 *
 * Distinct from the per-org `useWebhookDeliveries` hook in
 * `hooks/notifications/...` (if any exists for the customer-facing
 * webhooks UI). THIS hook calls `/api/v1/admin/webhook-deliveries`,
 * which is cross-tenant + admin-role-gated server-side.
 *
 * Why a new file (not appended to `useScraperRuns.ts`): same
 * revert-avoidance rationale as `useSlackDeliveries.ts` — the
 * upstream-revert pattern targets specific files; new files in
 * the admin/ namespace have so far survived.
 *
 * Two hooks:
 *
 *   * `useWebhookDeliveriesAdmin({ event_type?, status?,
 *      organization_id?, subscription_id?, limit? })` — paginated
 *      raw rows for the forensic table.
 *
 *   * `useWebhookDeliveriesAdminSummary(days)` — per-event-type
 *      rollup for the dashboard's summary cards.
 */

import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";


/** Allowed delivery status values. Mirrors the backend's
 *  `_ALLOWED_STATUSES` tuple in `routers/webhook_deliveries_admin.py`
 *  AND the dispatcher's state-machine literals in
 *  `services/webhooks.py`. A typo in this union catches at compile
 *  time rather than returning zero rows silently. */
export type WebhookDeliveryStatus =
  | "pending"
  | "in_flight"
  | "delivered"
  | "failed";


export const webhookDeliveriesAdminKeys = {
  all: ["admin", "webhook-deliveries"] as const,
  list: (
    eventType?: string | null,
    status?: WebhookDeliveryStatus | null,
    organizationId?: string | null,
    subscriptionId?: string | null,
    limit?: number,
  ) =>
    [
      ...webhookDeliveriesAdminKeys.all,
      "list",
      {
        event_type: eventType ?? null,
        status: status ?? null,
        organization_id: organizationId ?? null,
        subscription_id: subscriptionId ?? null,
        limit: limit ?? 50,
      },
    ] as const,
  summary: (days?: number) =>
    [...webhookDeliveriesAdminKeys.all, "summary", { days: days ?? 7 }] as const,
};


/** Mirrors `schemas.webhook_deliveries.WebhookDeliveryAdminOut`. */
export interface WebhookDeliveryAdminRow {
  id: string;
  organization_id: string;
  subscription_id: string;
  event_type: string;
  status: WebhookDeliveryStatus;
  attempt_count: number;
  response_status: number | null;
  response_body_snippet: string | null;
  error_message: string | null;
  next_retry_at: string | null;
  delivered_at: string | null;
  created_at: string;
}

/** Mirrors `schemas.webhook_deliveries.WebhookDeliveriesSummaryRow`. */
export interface WebhookDeliveriesAdminSummaryRow {
  event_type: string;
  total_attempts: number;
  delivered_count: number;
  failed_count: number;
  pending_count: number;
  delivered_rate: number | null;
  last_attempt_at: string | null;
  last_failure_at: string | null;
  last_failure_message: string | null;
  distinct_orgs: number;
  distinct_subscriptions: number;
}


export interface UseWebhookDeliveriesAdminOptions {
  /** Filter to one event type (e.g. "rfq.created"). */
  event_type?: string;
  /**
   * Filter on status. Tri-state semantics like `useSlackDeliveries`
   * — `undefined` = "all statuses"; pass an explicit status to
   * filter. The server validates against the allowed-status tuple
   * and 400s on a typo (better than zero-rows-silently).
   */
  status?: WebhookDeliveryStatus;
  /** Filter to one org id (cross-tenant drill-down). */
  organization_id?: string;
  /** Filter to one subscription id (per-receiver health view). */
  subscription_id?: string;
  /** Cap the page size — server enforces 1..500. Default 50. */
  limit?: number;
  /** Polling interval. Default off — caller opts in for live monitoring. */
  refetchIntervalMs?: number;
}


/**
 * `GET /api/v1/admin/webhook-deliveries` — recent deliveries
 * across all orgs.
 *
 * Server-side gating: `require_role("admin")`. A non-admin sees
 * the 403 surfaced as a query error.
 */
export function useWebhookDeliveriesAdmin({
  event_type,
  status,
  organization_id,
  subscription_id,
  limit = 50,
  refetchIntervalMs,
}: UseWebhookDeliveriesAdminOptions = {}) {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: webhookDeliveriesAdminKeys.list(
      event_type,
      status,
      organization_id,
      subscription_id,
      limit,
    ),
    queryFn: async () => {
      const res = await apiFetch<WebhookDeliveryAdminRow[]>(
        "/api/v1/admin/webhook-deliveries",
        {
          token,
          orgId,
          query: {
            event_type: event_type ?? null,
            // `status` is a tagged-union of valid strings — undefined
            // means "all". Don't send `status=null` on the wire; the
            // server's enum validation would 400 on the literal "null".
            ...(status === undefined ? {} : { status }),
            organization_id: organization_id ?? null,
            subscription_id: subscription_id ?? null,
            limit,
          },
        },
      );
      return res.data ?? [];
    },
    refetchInterval: refetchIntervalMs,
  });
}


/**
 * `GET /api/v1/admin/webhook-deliveries/summary` — per-event-type
 * aggregate over the last `days` days.
 *
 * Sorted server-side by delivery rate ASC NULLS LAST so the worst-
 * health event types surface first; the page preserves that order.
 */
export function useWebhookDeliveriesAdminSummary(days: number = 7) {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: webhookDeliveriesAdminKeys.summary(days),
    queryFn: async () => {
      const res = await apiFetch<WebhookDeliveriesAdminSummaryRow[]>(
        "/api/v1/admin/webhook-deliveries/summary",
        { token, orgId, query: { days } },
      );
      return res.data ?? [];
    },
  });
}


/** Detail row — same shape as the list row PLUS the customer payload.
 *  Mirrors `schemas.webhook_deliveries.WebhookDeliveryAdminDetailOut`. */
export interface WebhookDeliveryAdminDetail extends WebhookDeliveryAdminRow {
  payload: Record<string, unknown>;
}


/**
 * `GET /api/v1/admin/webhook-deliveries/{delivery_id}` — full forensic
 * detail for one delivery, including the payload that was sent. Drives
 * the `/admin/webhook-deliveries/[id]` drilldown page.
 *
 * Distinct from the list hook because the list endpoint omits payload
 * (cross-tenant ops shouldn't see every customer's payload while
 * skimming a 50-row triage table). The drilldown is the legitimate
 * "what did we actually send?" path.
 */
export function useWebhookDeliveryAdminDetail(deliveryId: string | undefined) {
  const { token, orgId } = useSession();
  return useQuery({
    enabled: Boolean(deliveryId),
    queryKey: deliveryId
      ? ([...webhookDeliveriesAdminKeys.all, "detail", deliveryId] as const)
      : (["admin", "webhook-deliveries", "detail", "noop"] as const),
    queryFn: async () => {
      const res = await apiFetch<WebhookDeliveryAdminDetail>(
        `/api/v1/admin/webhook-deliveries/${deliveryId}`,
        { token, orgId },
      );
      return res.data as WebhookDeliveryAdminDetail;
    },
  });
}
