/**
 * Audit resource route map (cycle R1).
 *
 * Pinned seams:
 *   1. Resource types in the map produce the correct in-app href.
 *   2. Unmapped resource_types fall back to `null` (graceful degrade
 *      — the audit page renders plain text instead of a dead link).
 *   3. Missing resource_id → null (no link to nowhere).
 */

import { describe, expect, it } from "vitest";

import {
  AUDIT_RESOURCE_ROUTES,
  auditResourceHref,
} from "../audit-resource-routes";


describe("auditResourceHref", () => {
  it("returns null when resource_type is missing", () => {
    expect(auditResourceHref(null, "abc")).toBeNull();
    expect(auditResourceHref(undefined, "abc")).toBeNull();
    expect(auditResourceHref("", "abc")).toBeNull();
  });

  it("returns null when resource_id is missing", () => {
    expect(auditResourceHref("change_orders", null)).toBeNull();
    expect(auditResourceHref("change_orders", undefined)).toBeNull();
    expect(auditResourceHref("change_orders", "")).toBeNull();
  });

  it("returns null for unmapped resource_types", () => {
    // Audit can carry these but they don't have a per-row resource
    // page worth jumping to (see the comment block in the routes
    // module). The page renders plain text instead of a dead link.
    expect(auditResourceHref("normalizer_rule", "00000000-0000-0000-0000-000000000001")).toBeNull();
    expect(auditResourceHref("invitations", "00000000-0000-0000-0000-000000000001")).toBeNull();
    expect(auditResourceHref("notification_preferences", "x")).toBeNull();
    expect(auditResourceHref("totally-unknown-type", "x")).toBeNull();
  });

  it("maps change_orders to /changeorder/<id> (singular path)", () => {
    // KEEP IN SYNC: the route was hoisted to the dashboard root
    // early in the project's lifecycle. A refactor that moves it
    // back under /pulse/changeorder/... would silently break audit
    // navigation.
    expect(auditResourceHref("change_orders", "abc-123")).toBe("/changeorder/abc-123");
  });

  it("maps punchlist_lists to /punchlist/<id> (different singular)", () => {
    // resource_type uses the plural `punchlist_lists`; the route is
    // singular `/punchlist/[id]`. Pin the asymmetry.
    expect(auditResourceHref("punchlist_lists", "abc-123")).toBe("/punchlist/abc-123");
  });

  it("maps webhook_subscription to /settings/webhooks/<id>", () => {
    // Cycle O1 added the `webhooks.subscription.rotate_secret`
    // audit; the row carries the subscription id so admins can
    // jump back to the rotation panel from the audit log during
    // an incident retro.
    expect(auditResourceHref("webhook_subscription", "abc-123")).toBe(
      "/settings/webhooks/abc-123",
    );
  });

  it("maps each entry to a function returning a non-empty href", () => {
    // Sanity: every entry in the map produces a valid-looking
    // href when given a sample id. Catches a refactor that
    // accidentally hard-codes an empty path.
    for (const [resourceType, route] of Object.entries(AUDIT_RESOURCE_ROUTES)) {
      const href = route("00000000-0000-0000-0000-000000000001");
      expect(href, `route for ${resourceType} returned empty`).toMatch(/^\/.+/);
    }
  });
});
