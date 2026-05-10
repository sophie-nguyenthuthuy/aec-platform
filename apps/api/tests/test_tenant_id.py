"""Multi-tenant ID prefix validator (cycle XX3).

Pinned seams:
  1. `org_` prefix required.
  2. Strict (exact) slug match — substring-prefix doesn't pass.
  3. Case-sensitive.
  4. Empty / None either side → False / None.
  5. `extract_tenant_prefix` returns first segment.
"""

from __future__ import annotations

from services.tenant_id import belongs_to_org, extract_tenant_prefix

# ---------- belongs_to_org ----------


def test_canonical_match():
    assert belongs_to_org("org_acme_user_42", "acme") is True


def test_different_resource_type_same_org():
    assert belongs_to_org("org_acme_estimate_123", "acme") is True
    assert belongs_to_org("org_acme_punchlist_99", "acme") is True


def test_cross_tenant_rejected():
    """Cardinal pin: cross-tenant ID rejected."""
    assert belongs_to_org("org_other_user_42", "acme") is False


def test_substring_prefix_rejected():
    """Cardinal pin: `org_acmecorp_*` does NOT belong to `acme`.
    Pin against a substring-prefix bug — the underscore boundary
    must be EXACT."""
    assert belongs_to_org("org_acmecorp_user_42", "acme") is False
    assert belongs_to_org("org_acm_user_42", "acme") is False


def test_no_org_prefix_rejected():
    """Resource IDs without `org_` prefix are rejected. Pin
    against legacy non-tenant-prefixed IDs slipping past."""
    assert belongs_to_org("user_42", "acme") is False
    assert belongs_to_org("acme_user_42", "acme") is False


def test_case_sensitive():
    """Pin: case-sensitive comparison (org slugs are lowercase
    canonical via CC3)."""
    assert belongs_to_org("org_ACME_user_42", "acme") is False
    assert belongs_to_org("org_acme_user_42", "ACME") is False


def test_none_resource_id_returns_false():
    assert belongs_to_org(None, "acme") is False


def test_none_org_id_returns_false():
    """Cardinal pin: None org_id → False. Defends against a
    refactor that treats null tenancy as "match anything"."""
    assert belongs_to_org("org_acme_user_42", None) is False


def test_empty_either_side_returns_false():
    assert belongs_to_org("", "acme") is False
    assert belongs_to_org("org_acme_user_42", "") is False
    assert belongs_to_org("", "") is False


# ---------- extract_tenant_prefix ----------


def test_extract_simple():
    assert extract_tenant_prefix("org_acme_user_42") == "acme"


def test_extract_different_resource_types():
    assert extract_tenant_prefix("org_acme_estimate_123") == "acme"
    assert extract_tenant_prefix("org_acme_punchlist_99") == "acme"


def test_extract_first_segment_only():
    """Pin: extracts the FIRST segment after `org_`. Multi-word
    slugs aren't supported (CC3 canonical slugs are single
    hyphens, never underscores)."""
    # `hung-vuong-corp` is the canonical slug; in the resource
    # ID it's `org_hung-vuong-corp_user_42` (hyphen preserved
    # in slug, underscore separates segments).
    assert extract_tenant_prefix("org_hung-vuong-corp_user_42") == "hung-vuong-corp"


def test_extract_no_org_prefix_returns_none():
    assert extract_tenant_prefix("user_42") is None
    assert extract_tenant_prefix("acme_user_42") is None


def test_extract_empty_slug_returns_none():
    """`org__user_42` (empty slug) → None."""
    assert extract_tenant_prefix("org__user_42") is None


def test_extract_org_only_returns_none():
    """Just `org_` with nothing after → None."""
    assert extract_tenant_prefix("org_") is None


def test_extract_org_acme_no_inner_underscore_returns_none():
    """`org_acme` (no inner underscore for resource type) → None."""
    assert extract_tenant_prefix("org_acme") is None


def test_extract_none_returns_none():
    assert extract_tenant_prefix(None) is None


def test_extract_empty_returns_none():
    assert extract_tenant_prefix("") is None


# ---------- Realistic ----------


def test_realistic_audit_row_tenant_check():
    """Realistic: audit row's resource_id is checked against
    request's claimed org_id."""
    audit_resource_id = "org_acme_estimate_42"
    request_org_id = "acme"
    assert belongs_to_org(audit_resource_id, request_org_id) is True

    # Cross-tenant attempt: same audit row, different request org.
    assert belongs_to_org(audit_resource_id, "other") is False


def test_realistic_extract_for_cross_tenant_audit_grouping():
    """Realistic: platform-admin dashboard groups audit events
    by extracted tenant prefix to render per-org rollups."""
    resource_ids = [
        "org_acme_user_1",
        "org_acme_user_2",
        "org_other_user_3",
        "org_third_estimate_99",
    ]
    tenants = [extract_tenant_prefix(r) for r in resource_ids]
    assert tenants == ["acme", "acme", "other", "third"]
