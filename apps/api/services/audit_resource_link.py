"""Server-side audit resource URL builder (cycle X2).

Backend complement to `apps/web/lib/audit-resource-routes.ts` (R1).
Same per-resource-type route map, surfaced server-side so:

  * Webhook payloads can include a `resource_url` field — partner
    integrations get a clickable deep-link without re-implementing
    the route map.
  * Slack alerts on audit-rule triggers (future) carry clickable
    refs to the resource page.
  * CSV exports (P3 / W2) can add a `link` column for compliance
    reviewers who want to navigate from the spreadsheet.
  * Email digests of pinned audit rows (V1 + future) include the
    resource URL inline.

The mapping MUST stay in lock-step with the frontend's
`AUDIT_RESOURCE_ROUTES`. Adding a new resource type = touch in
both files; tests in both pin the relevant entries.

Pure Python — no DB. The caller supplies a base URL (the org's
deployment hostname); this helper composes the path.
"""

from __future__ import annotations

# Per-resource-type path templates. Mirror of the frontend's
# `AUDIT_RESOURCE_ROUTES` map. Keys are the `audit_events.resource_type`
# values; values are URL paths with `{id}` placeholder.
#
# Adding a new entry: also add one to
# `apps/web/lib/audit-resource-routes.ts`. The cross-language
# surface tests pin both directions.
AUDIT_RESOURCE_PATHS: dict[str, str] = {
    "estimates": "/costpulse/estimates/{id}",
    "rfq": "/costpulse/rfq/{id}",
    "change_orders": "/changeorder/{id}",
    "handover_packages": "/handover/{id}",
    "punchlist_lists": "/punchlist/{id}",
    "submittals": "/submittals/{id}",
    "webhook_subscription": "/settings/webhooks/{id}",
}


def resource_url(
    *,
    base_url: str,
    resource_type: str | None,
    resource_id: str | None,
) -> str | None:
    """Compose a deep-link URL for an audit row's resource.

    Returns `None` when:
      * `resource_type` is None / empty
      * `resource_id` is None / empty
      * `resource_type` isn't in the route map (graceful degrade —
        the partner sees the audit row without a link rather than
        a broken URL)

    `base_url` is the deployment's hostname (e.g.
    `https://app.aec-platform.vn`). Trailing slash tolerated;
    we always strip then prepend the path with `/`.

    Defensive: a `resource_id` that contains characters bad for a
    URL path (whitespace, `?`, `#`) is the caller's bug — the
    audit row's `resource_id` is a UUID, validated at write time.
    The helper does NOT URL-encode here; that would make a UUID
    look ugly in the partner's link.
    """
    if not resource_type or not resource_id:
        return None
    template = AUDIT_RESOURCE_PATHS.get(resource_type)
    if template is None:
        return None
    path = template.format(id=resource_id)
    base = base_url.rstrip("/")
    return f"{base}{path}"


def supports_deep_link(resource_type: str | None) -> bool:
    """Cheap predicate: does this resource_type have a route?

    Used by the CSV export (W2) + Slack alert formatter to decide
    whether to include a `link` column / suffix at all. A row
    whose resource_type isn't mapped renders without the link
    column.
    """
    if not resource_type:
        return False
    return resource_type in AUDIT_RESOURCE_PATHS
