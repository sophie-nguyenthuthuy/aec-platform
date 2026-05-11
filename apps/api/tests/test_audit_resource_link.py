"""Server-side audit resource URL helper (cycle X2).

Pinned seams:
  1. Mapped resource_type produces an absolute URL.
  2. Unmapped resource_type → None (graceful degrade).
  3. Missing id / empty type → None (no broken links in webhook
     payloads).
  4. `base_url` trailing slash tolerated.
  5. Per-resource-type path templates pinned — drift between this
     file and `apps/web/lib/audit-resource-routes.ts` would break
     navigation when the URL is followed.
"""

from __future__ import annotations

from services.audit_resource_link import (
    AUDIT_RESOURCE_PATHS,
    resource_url,
    supports_deep_link,
)

# ---------- supports_deep_link ----------


def test_supports_deep_link_for_mapped_types():
    assert supports_deep_link("change_orders") is True
    assert supports_deep_link("punchlist_lists") is True
    assert supports_deep_link("webhook_subscription") is True


def test_supports_deep_link_false_for_unmapped():
    assert supports_deep_link("normalizer_rule") is False
    assert supports_deep_link("invitations") is False
    assert supports_deep_link(None) is False
    assert supports_deep_link("") is False


# ---------- resource_url ----------


def test_resource_url_composes_change_orders_path():
    """change_orders resource_type → /changeorder/<id> (singular
    path; KEEP IN SYNC with the frontend route map)."""
    out = resource_url(
        base_url="https://app.aec-platform.vn",
        resource_type="change_orders",
        resource_id="abc-123",
    )
    assert out == "https://app.aec-platform.vn/changeorder/abc-123"


def test_resource_url_composes_punchlist_path():
    """punchlist_lists (plural in resource_type) → /punchlist/<id>
    (singular in route). Pin the asymmetry."""
    out = resource_url(
        base_url="https://app.aec-platform.vn",
        resource_type="punchlist_lists",
        resource_id="abc-123",
    )
    assert out == "https://app.aec-platform.vn/punchlist/abc-123"


def test_resource_url_composes_webhook_subscription_path():
    """Cycle O1's webhook subscription rotate_secret audit carries
    the subscription id — should link back to /settings/webhooks/[id]."""
    out = resource_url(
        base_url="https://app.aec-platform.vn",
        resource_type="webhook_subscription",
        resource_id="sub-xyz",
    )
    assert out == "https://app.aec-platform.vn/settings/webhooks/sub-xyz"


def test_resource_url_none_for_unmapped_resource_type():
    """Graceful degrade — partner sees the audit row without a
    link rather than getting a 404 from a broken URL."""
    out = resource_url(
        base_url="https://app.aec-platform.vn",
        resource_type="normalizer_rule",
        resource_id="abc",
    )
    assert out is None


def test_resource_url_none_for_missing_inputs():
    """Defensive against the audit row's nullable fields."""
    base = "https://app.aec-platform.vn"
    assert resource_url(base_url=base, resource_type=None, resource_id="abc") is None
    assert resource_url(base_url=base, resource_type="", resource_id="abc") is None
    assert resource_url(base_url=base, resource_type="change_orders", resource_id=None) is None
    assert resource_url(base_url=base, resource_type="change_orders", resource_id="") is None


def test_resource_url_strips_trailing_slash_from_base():
    """Tolerate a base_url with or without a trailing slash —
    composing config tends to vary across deployments."""
    a = resource_url(
        base_url="https://app.aec-platform.vn/",
        resource_type="change_orders",
        resource_id="abc",
    )
    b = resource_url(
        base_url="https://app.aec-platform.vn",
        resource_type="change_orders",
        resource_id="abc",
    )
    assert a == b == "https://app.aec-platform.vn/changeorder/abc"


# ---------- Path map shape ----------


def test_audit_resource_paths_set_pinned():
    """The set of resource_types with deep links MUST match the
    frontend's `AUDIT_RESOURCE_ROUTES`. Drift = the link in a
    webhook payload points at a route the frontend doesn't render
    (or vice versa, an audit row with no link in the UI but a
    link in the webhook payload).

    Pin the exact set so a refactor that adds an entry server-
    side without updating the frontend (or vice versa) fails this
    test."""
    expected = {
        "estimates",
        "rfq",
        "change_orders",
        "handover_packages",
        "punchlist_lists",
        "submittals",
        "webhook_subscription",
    }
    assert set(AUDIT_RESOURCE_PATHS.keys()) == expected


def test_audit_resource_paths_all_use_id_placeholder():
    """Every template MUST use `{id}` as the placeholder. Pin
    so a refactor that switches to f-strings doesn't silently
    skip the substitution."""
    for resource_type, template in AUDIT_RESOURCE_PATHS.items():
        assert "{id}" in template, f"Template for {resource_type!r} doesn't use {{id}} placeholder: {template!r}"
        assert template.startswith("/"), f"Template for {resource_type!r} must be an absolute path"
