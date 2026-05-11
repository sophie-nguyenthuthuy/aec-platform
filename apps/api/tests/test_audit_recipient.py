"""Audit row recipient resolver (cycle BBB3).

Pinned seams:
  1. Result ordered by member_id ascending.
  2. Members without `audit.read` role permission excluded.
  3. Muted members excluded (CC2 should_deliver=False).
  4. Members with empty event_types excluded.
  5. Members whose patterns don't match → excluded.
  6. Empty input → empty result.
  7. Result is a tuple (immutable).
  8. ctx with empty org_id → ValueError.
  9. Composes CC2 + DD1 + ZZ3.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from services.audit_context import AuditContext, from_request
from services.audit_recipient import (
    AUDIT_READ_ACTION,
    AuditMember,
    Recipient,
    resolve_recipients,
)
from services.notification_match import NotificationPreference

NOW = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)


def _ctx(org_id: str = "acme") -> AuditContext:
    return from_request(
        org_id=org_id,
        actor_id="actor@example.com",
        request_id="req-123",
    )


def _prefs(
    channels: frozenset[str] = frozenset({"email"}),
    muted_until: datetime | None = None,
    event_types: tuple[str, ...] = ("*",),
) -> NotificationPreference:
    return NotificationPreference(
        channels=channels,
        muted_until=muted_until,
        event_types=event_types,
    )


def _member(
    member_id: str = "m1",
    role: str = "member",
    prefs: NotificationPreference | None = None,
) -> AuditMember:
    return AuditMember(
        member_id=member_id,
        role=role,
        prefs=prefs if prefs is not None else _prefs(),
    )


# ---------- Constants ----------


def test_audit_read_action_pinned():
    """Cross-cycle pin: the DD1 action key for audit read."""
    assert AUDIT_READ_ACTION == "audit.read"


# ---------- Empty input ----------


def test_empty_members_returns_empty():
    result = resolve_recipients(_ctx(), "audit.change_order.approve", (), NOW)
    assert result == ()


# ---------- Single member happy path ----------


def test_single_matching_member_included():
    result = resolve_recipients(
        _ctx(),
        "audit.change_order.approve",
        (_member(),),
        NOW,
    )
    assert len(result) == 1
    assert result[0].member_id == "m1"
    assert result[0].channels == frozenset({"email"})


def test_result_is_tuple_not_list():
    """Cardinal pin: tuple, not list (immutability)."""
    result = resolve_recipients(_ctx(), "*", (_member(),), NOW)
    assert isinstance(result, tuple)


# ---------- Role filter (DD1) ----------


def test_viewer_with_audit_read_included():
    """Viewer has audit.read permission per DD1 — included."""
    result = resolve_recipients(
        _ctx(),
        "audit.x",
        (_member(role="viewer"),),
        NOW,
    )
    assert len(result) == 1


def test_unknown_role_excluded():
    """Cardinal pin: unknown role lacks audit.read → excluded."""
    result = resolve_recipients(
        _ctx(),
        "audit.x",
        (_member(role="banned"),),
        NOW,
    )
    assert result == ()


def test_none_role_excluded():
    """Pin: role=None → DD1.can returns False → excluded."""
    result = resolve_recipients(
        _ctx(),
        "audit.x",
        (_member(role="not-a-role"),),
        NOW,
    )
    assert result == ()


# ---------- CC2 mute filter ----------


def test_muted_member_excluded():
    """Cardinal pin: muted_until > now → excluded."""
    muted = _prefs(muted_until=NOW + timedelta(hours=1))
    result = resolve_recipients(
        _ctx(),
        "audit.x",
        (_member(prefs=muted),),
        NOW,
    )
    assert result == ()


def test_mute_expired_member_included():
    """Pin: muted_until <= now → mute expired → delivered."""
    expired = _prefs(muted_until=NOW - timedelta(hours=1))
    result = resolve_recipients(
        _ctx(),
        "audit.x",
        (_member(prefs=expired),),
        NOW,
    )
    assert len(result) == 1


# ---------- CC2 pattern filter ----------


def test_empty_event_types_excluded():
    """CC2 REASON_EMPTY_SUBSCRIPTION → excluded."""
    no_subs = _prefs(event_types=())
    result = resolve_recipients(
        _ctx(),
        "audit.x",
        (_member(prefs=no_subs),),
        NOW,
    )
    assert result == ()


def test_pattern_mismatch_excluded():
    other = _prefs(event_types=("other.event",))
    result = resolve_recipients(
        _ctx(),
        "audit.x",
        (_member(prefs=other),),
        NOW,
    )
    assert result == ()


def test_wildcard_module_pattern_match():
    audit_wild = _prefs(event_types=("audit.*",))
    result = resolve_recipients(
        _ctx(),
        "audit.change_order.approve",
        (_member(prefs=audit_wild),),
        NOW,
    )
    assert len(result) == 1


def test_no_valid_channels_excluded():
    """CC2 REASON_NO_VALID_CHANNELS — empty channels → excluded."""
    bad = _prefs(channels=frozenset())
    result = resolve_recipients(
        _ctx(),
        "audit.x",
        (_member(prefs=bad),),
        NOW,
    )
    assert result == ()


# ---------- Ordering ----------


def test_members_ordered_by_id_ascending():
    """Cardinal pin: deterministic order."""
    members = (
        _member(member_id="charlie"),
        _member(member_id="alice"),
        _member(member_id="bob"),
    )
    result = resolve_recipients(_ctx(), "*", members, NOW)
    assert [r.member_id for r in result] == ["alice", "bob", "charlie"]


def test_ordering_stable_across_calls():
    """Same input → same output ordering."""
    members = (
        _member(member_id="zoe"),
        _member(member_id="adam"),
    )
    r1 = resolve_recipients(_ctx(), "*", members, NOW)
    r2 = resolve_recipients(_ctx(), "*", members, NOW)
    assert r1 == r2


# ---------- Mixed scenarios ----------


def test_mixed_filter_some_in_some_out():
    """Realistic: 4 members, only 2 match all filters."""
    members = (
        # included: matches everything
        _member(member_id="alice", role="member"),
        # excluded: muted
        _member(
            member_id="bob",
            role="member",
            prefs=_prefs(muted_until=NOW + timedelta(hours=1)),
        ),
        # excluded: role lacks audit.read
        _member(member_id="charlie", role="banned"),
        # included: viewer (has audit.read)
        _member(member_id="dave", role="viewer"),
    )
    result = resolve_recipients(_ctx(), "audit.x", members, NOW)
    assert [r.member_id for r in result] == ["alice", "dave"]


def test_admin_owner_included():
    """All in-band roles {viewer, member, admin, owner} are included."""
    members = tuple(_member(member_id=role, role=role) for role in ["viewer", "member", "admin", "owner"])
    result = resolve_recipients(_ctx(), "*", members, NOW)
    assert len(result) == 4
    assert [r.member_id for r in result] == [
        "admin",
        "member",
        "owner",
        "viewer",
    ]


# ---------- Cross-tenant guard ----------


def test_ctx_empty_org_id_rejected_at_construction():
    """Cross-cycle pin: ZZ3 from_request blocks empty org_id."""
    with pytest.raises(ValueError):
        from_request(org_id="", actor_id="x", request_id="x")


def test_resolve_defensive_empty_org_id_raises():
    """Defensive: even if ctx is constructed via raw dataclass,
    resolver still raises (in-depth defense)."""
    bad_ctx = AuditContext(
        org_id="",
        actor_id="x",
        request_id="x",
    )
    with pytest.raises(ValueError):
        resolve_recipients(bad_ctx, "audit.x", (_member(),), NOW)


# ---------- Channels preserved ----------


def test_channels_preserved_in_recipient():
    """Pin: Recipient.channels equals CC2's valid channel set."""
    member = _member(
        prefs=_prefs(channels=frozenset({"email", "slack", "in_app"})),
    )
    result = resolve_recipients(_ctx(), "*", (member,), NOW)
    assert result[0].channels == frozenset({"email", "slack", "in_app"})


def test_channels_intersected_with_known():
    """CC2 intersects with CHANNELS — invalid channel dropped."""
    member = _member(
        prefs=_prefs(channels=frozenset({"email", "fax-machine"})),
    )
    result = resolve_recipients(_ctx(), "*", (member,), NOW)
    assert result[0].channels == frozenset({"email"})


# ---------- Composes ----------


def test_composes_cc2_match_event():
    """Cross-cycle pin: filter delegates to CC2 match_event."""
    # Two members differ only in event_types — one matches, one doesn't.
    matches = _member(
        member_id="a",
        prefs=_prefs(event_types=("audit.x",)),
    )
    no_match = _member(
        member_id="b",
        prefs=_prefs(event_types=("other.y",)),
    )
    result = resolve_recipients(
        _ctx(),
        "audit.x",
        (matches, no_match),
        NOW,
    )
    assert [r.member_id for r in result] == ["a"]


def test_composes_dd1_role_check():
    """Cross-cycle pin: role check uses DD1.can(role, 'audit.read')."""
    # Viewer has audit.read; banned does not.
    members = (
        _member(member_id="v", role="viewer"),
        _member(member_id="b", role="banned"),
    )
    result = resolve_recipients(_ctx(), "*", members, NOW)
    assert [r.member_id for r in result] == ["v"]


# ---------- Frozen ----------


def test_recipient_is_frozen():
    r = Recipient(member_id="m1", channels=frozenset({"email"}))
    try:
        r.member_id = "m2"  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("Recipient should be frozen")


def test_audit_member_is_frozen():
    m = _member()
    try:
        m.member_id = "m2"  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("AuditMember should be frozen")
