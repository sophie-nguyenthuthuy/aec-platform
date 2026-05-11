"""Audit context builder (cycle ZZ3 — 30th-cycle capstone).

Pinned seams:
  1. org_id required at construction.
  2. with_resource returns NEW ctx (frozen — immutable).
  3. dedup_key_for composes QQ1.
  4. fingerprint_for composes RR3.
  5. validate_resource_belongs composes XX3.
  6. request_id NOT used in dedup/fingerprint.
"""

from __future__ import annotations

import pytest

from services.audit_context import (
    dedup_key_for,
    fingerprint_for,
    from_request,
    validate_resource_belongs,
    with_resource,
)
from services.audit_fingerprint import fingerprint as _direct_fingerprint
from services.tenant_id import belongs_to_org
from services.webhook_dedup_key import dedup_key as _direct_dedup_key

# ---------- Construction ----------


def test_from_request_basic():
    ctx = from_request("acme", "user@x.com", "req-1")
    assert ctx.org_id == "acme"
    assert ctx.actor_id == "user@x.com"
    assert ctx.request_id == "req-1"
    assert ctx.resource_id == ""  # default


def test_from_request_empty_org_id_raises():
    """Cardinal pin: org_id REQUIRED at construction. Cross-
    tenant guard fails fast at request parse."""
    with pytest.raises(ValueError):
        from_request("", "user@x.com", "req-1")


def test_from_request_other_empty_fields_allowed():
    """Pin: only org_id is required. Empty actor_id /
    request_id allowed (system actions / no-correlation)."""
    ctx = from_request("acme", "", "")
    assert ctx.org_id == "acme"


# ---------- Immutability ----------


def test_audit_context_is_frozen():
    ctx = from_request("acme", "u", "r")
    try:
        ctx.org_id = "other"  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("AuditContext should be frozen")


def test_with_resource_returns_new_context():
    """Pin: with_resource is non-mutating — returns NEW ctx."""
    ctx = from_request("acme", "u", "r")
    ctx2 = with_resource(ctx, "res-1")
    assert ctx2 is not ctx
    assert ctx.resource_id == ""  # original unchanged
    assert ctx2.resource_id == "res-1"
    # Other fields preserved.
    assert ctx2.org_id == "acme"
    assert ctx2.actor_id == "u"
    assert ctx2.request_id == "r"


def test_with_resource_chainable():
    """Pin: subsequent with_resource overwrites previous."""
    ctx = from_request("acme", "u", "r")
    ctx2 = with_resource(ctx, "res-1")
    ctx3 = with_resource(ctx2, "res-2")
    assert ctx3.resource_id == "res-2"
    # Earlier ctx unchanged.
    assert ctx2.resource_id == "res-1"


# ---------- Composes with QQ1 ----------


def test_dedup_key_for_composes_qq1():
    """Cross-cycle pin: dedup_key_for output equals direct
    QQ1.dedup_key call with org_id as subscription_id."""
    ctx = with_resource(from_request("acme", "u", "r"), "res-42")
    composed = dedup_key_for(ctx, "create", "hash1234567890123456")
    direct = _direct_dedup_key(
        subscription_id="acme",
        event_type="create",
        resource_id="res-42",
        payload_hash="hash1234567890123456",
    )
    assert composed == direct


def test_dedup_key_deterministic():
    ctx = with_resource(from_request("acme", "u", "r"), "res-1")
    a = dedup_key_for(ctx, "create", "h" * 16)
    b = dedup_key_for(ctx, "create", "h" * 16)
    assert a == b


def test_dedup_key_different_orgs_different():
    ctx_a = with_resource(from_request("acme", "u", "r"), "res-1")
    ctx_b = with_resource(from_request("other", "u", "r"), "res-1")
    a = dedup_key_for(ctx_a, "create", "h" * 16)
    b = dedup_key_for(ctx_b, "create", "h" * 16)
    assert a != b


# ---------- Composes with RR3 ----------


def test_fingerprint_for_composes_rr3():
    """Cross-cycle pin: fingerprint_for equals direct
    RR3.fingerprint call."""
    ctx = with_resource(from_request("acme", "u@x.com", "r"), "res-1")
    composed = fingerprint_for(ctx, "create", "diffhash" * 4)
    direct = _direct_fingerprint(
        org_id="acme",
        actor_id="u@x.com",
        action="create",
        resource_id="res-1",
        payload_diff_hash="diffhash" * 4,
    )
    assert composed == direct


def test_fingerprint_deterministic():
    ctx = with_resource(from_request("acme", "u", "r"), "res-1")
    a = fingerprint_for(ctx, "create", "h" * 16)
    b = fingerprint_for(ctx, "create", "h" * 16)
    assert a == b


def test_fingerprint_different_actors_different():
    ctx_a = with_resource(from_request("acme", "alice", "r"), "res-1")
    ctx_b = with_resource(from_request("acme", "bob", "r"), "res-1")
    a = fingerprint_for(ctx_a, "create", "h" * 16)
    b = fingerprint_for(ctx_b, "create", "h" * 16)
    assert a != b


# ---------- request_id NOT in dedup/fingerprint ----------


def test_request_id_not_in_dedup_key():
    """Cardinal pin: request_id is correlation-only, NOT used
    in dedup. Two requests with same content (different
    request_ids) MUST dedupe to the same key. Pin so a
    refactor that includes request_id breaks here."""
    ctx_a = with_resource(from_request("acme", "u", "req-A"), "res-1")
    ctx_b = with_resource(from_request("acme", "u", "req-B"), "res-1")
    a = dedup_key_for(ctx_a, "create", "h" * 16)
    b = dedup_key_for(ctx_b, "create", "h" * 16)
    assert a == b


def test_request_id_not_in_fingerprint():
    """Pin: request_id NOT in fingerprint either. Same logical
    event from two different requests has same fingerprint."""
    ctx_a = with_resource(from_request("acme", "u", "req-A"), "res-1")
    ctx_b = with_resource(from_request("acme", "u", "req-B"), "res-1")
    a = fingerprint_for(ctx_a, "create", "h" * 16)
    b = fingerprint_for(ctx_b, "create", "h" * 16)
    assert a == b


# ---------- Composes with XX3 ----------


def test_validate_resource_belongs_composes_xx3():
    """Cross-cycle pin: validate_resource_belongs delegates to
    XX3's belongs_to_org."""
    ctx = from_request("acme", "u", "r")
    assert validate_resource_belongs(ctx, "org_acme_estimate_42") is True
    assert validate_resource_belongs(ctx, "org_other_estimate_42") is False

    # Direct XX3 call agrees.
    assert belongs_to_org("org_acme_estimate_42", "acme") is True


def test_validate_cross_tenant_rejected():
    """Cardinal pin: cross-tenant resource ID rejected."""
    ctx = from_request("acme", "u", "r")
    assert validate_resource_belongs(ctx, "org_evil_estimate_42") is False


# ---------- Capstone end-to-end ----------


def test_capstone_full_audit_emit_chain():
    """30th-cycle capstone: full audit emit chain in one go.
    Composes XX3 + QQ1 + RR3 via this single helper. Pin the
    end-to-end flow as the canonical pattern for audit emits."""
    # Build context from request fields.
    ctx = from_request(
        org_id="acme",
        actor_id="user@example.com",
        request_id="req-12345",
    )

    # Bind to a resource.
    ctx_resource = with_resource(ctx, "org_acme_estimate_42")

    # Step 1: Validate cross-tenant (XX3).
    assert validate_resource_belongs(ctx_resource, "org_acme_estimate_42") is True
    assert validate_resource_belongs(ctx_resource, "org_other_estimate_42") is False

    # Step 2: Compute dedup key (QQ1).
    dedup = dedup_key_for(ctx_resource, "estimate.update", "h" * 32)
    assert len(dedup) == 64  # SHA-256 hex

    # Step 3: Compute fingerprint (RR3).
    fp = fingerprint_for(ctx_resource, "estimate.update", "diff" * 16)
    assert len(fp) == 64

    # Step 4: Re-running the same context produces same outputs
    # (the dedup primitive — pin idempotency).
    dedup2 = dedup_key_for(ctx_resource, "estimate.update", "h" * 32)
    assert dedup == dedup2

    fp2 = fingerprint_for(ctx_resource, "estimate.update", "diff" * 16)
    assert fp == fp2


def test_capstone_imports_three_prior_cycles():
    """Pin: this capstone imports XX3 + QQ1 + RR3 directly.
    Verify the imports compose as expected — every prior-cycle
    helper is callable through the AuditContext interface."""
    ctx = with_resource(from_request("acme", "alice", "r-1"), "org_acme_x_1")

    # XX3 path.
    xx3_result = validate_resource_belongs(ctx, "org_acme_x_1")
    assert isinstance(xx3_result, bool)

    # QQ1 path.
    qq1_result = dedup_key_for(ctx, "ev", "hash")
    assert isinstance(qq1_result, str)
    assert len(qq1_result) == 64

    # RR3 path.
    rr3_result = fingerprint_for(ctx, "ev", "diff")
    assert isinstance(rr3_result, str)
    assert len(rr3_result) == 64
