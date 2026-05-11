/**
 * Map from `audit_events.resource_type` → in-app route for the
 * resource (cycle R1).
 *
 * Closes the "I see the audit row but where's the actual change
 * order?" friction. Clicking a `resource_id` in the audit log jumps
 * straight to the resource page.
 *
 * Why a frontend-side map rather than a server-rendered href: the
 * audit log is read-only telemetry. The resource_type vocabulary
 * lives in `services/audit.py` (the `record(..., resource_type=...)`
 * call sites); the navigation routes live in the Next.js app. A
 * frontend table that joins the two is the lightest touch and
 * keeps the API surface stable.
 *
 * Adding a new resource_type:
 *   1. Add the call site in services/audit.py with the new
 *      resource_type string.
 *   2. Add an entry below mapping it to a `(id) => href` function.
 *
 * If the audit row's resource_type isn't in the map, the row
 * renders the id as plain text (no jump affordance) — graceful
 * degradation rather than a 404.
 */

// Each value is a function from `resource_id` (string UUID) to a
// route href. A function rather than a template string keeps room
// for future shapes that need additional path segments (e.g.
// "/projects/<project_id>/changeorder/<id>" — would require
// threading the project_id through the audit row, but the function
// signature is ready for it).
export type AuditResourceRoute = (resourceId: string) => string;


// Per-resource-type route map. Keys mirror `services/audit.AuditAction`'s
// `resource_type` arguments — KEEP IN SYNC: when adding a new audit
// resource type server-side, add the route here.
export const AUDIT_RESOURCE_ROUTES: Record<string, AuditResourceRoute> = {
  // CostPulse
  estimates: (id) => `/costpulse/estimates/${id}`,
  rfq: (id) => `/costpulse/rfq/${id}`,
  // ProjectPulse — change orders live at `/changeorder/[id]` (NOT
  // `/pulse/changeorder/...`); the route was hoisted to the
  // dashboard root early in the project's lifecycle.
  change_orders: (id) => `/changeorder/${id}`,
  // Handover
  handover_packages: (id) => `/handover/${id}`,
  // Punch list — singular `punchlist` in route, plural in
  // resource_type. Pin so a refactor that rewrites the route
  // without updating this map silently breaks navigation.
  punchlist_lists: (id) => `/punchlist/${id}`,
  // Submittals
  submittals: (id) => `/submittals/${id}`,
  // Webhook subscriptions — cycle O1 adds `webhooks.subscription.rotate_secret`
  // audit events that carry the subscription id.
  webhook_subscription: (id) => `/settings/webhooks/${id}`,
  // ---------- Resource types deliberately NOT mapped ----------
  // The following resource types CAN be audited but don't have a
  // resource page worth jumping to. A row with these types renders
  // the id as plain text rather than an empty link.
  //
  //   * `org_members` — the row's resource_id is a user UUID; the
  //     org members listing isn't keyed by user id.
  //   * `invitations` — invitations expire/get accepted; deep-link
  //     to a stale row would 404.
  //   * `boq_items` — line items inside an estimate; jumping to the
  //     parent estimate is more useful, but the audit row carries
  //     only the item id.
  //   * `suppliers` — there's a /costpulse/suppliers list but no
  //     per-supplier page yet.
  //   * `notification_preferences` — preferences are part of
  //     /settings/notifications; no per-row deep link.
  //   * `normalizer_rule` — admin-only resource at /admin/normalizer-rules,
  //     and the audit org_id may differ from the rule's tenant —
  //     better to keep operators in admin context manually.
  //   * `cron` — cycle O2 manual cron run carries `resource_id=None`,
  //     so there's nothing to link to anyway.
};


/**
 * Resolve a deep-link href for an audit row, or `null` if the
 * resource_type isn't mapped or `resource_id` is missing.
 *
 * Pure helper so the audit page renders synchronously without a
 * useMemo / hook layer.
 */
export function auditResourceHref(
  resourceType: string | null | undefined,
  resourceId: string | null | undefined,
): string | null {
  if (!resourceType || !resourceId) return null;
  const route = AUDIT_RESOURCE_ROUTES[resourceType];
  if (!route) return null;
  return route(resourceId);
}
