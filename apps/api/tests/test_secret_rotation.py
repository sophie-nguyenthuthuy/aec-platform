"""Webhook secret rotation grace window (cycle KK2).

Pinned seams:
  1. DEFAULT_GRACE_SECONDS = 86400 (24h).
  2. MAX_GRACE_SECONDS = 604800 (7d).
  3. Outside grace: only current_secret validates.
  4. Inside grace: both validated; matched label returned.
  5. previous_secret=None → no grace path attempted.
  6. rotated_at=None → no grace path attempted.
  7. Strict `>=` grace boundary.
  8. Grace clamped to [0, MAX].
  9. matches called at most twice.
 10. Current tried before previous (cost / happy-path pin).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from services.secret_rotation import (
    DEFAULT_GRACE_SECONDS,
    MAX_GRACE_SECONDS,
    is_signature_valid_during_rotation,
)

ROTATED_AT = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)
IN_GRACE = ROTATED_AT + timedelta(hours=12)
OUT_OF_GRACE = ROTATED_AT + timedelta(hours=25)
AT_GRACE_BOUNDARY = ROTATED_AT + timedelta(seconds=DEFAULT_GRACE_SECONDS)


def _matches_only(secret_label: str, calls: list[str] | None = None):
    """Build a `matches` callback that returns True only for
    the specified secret label."""

    def matches(secret: str) -> bool:
        if calls is not None:
            calls.append(secret)
        return secret == secret_label

    return matches


# ---------- Constants ----------


def test_default_grace_is_24h():
    """24h is the operationally common grace window. Pin so a
    refactor that drops surfaces here."""
    assert DEFAULT_GRACE_SECONDS == 86400


def test_max_grace_is_7d():
    """Legal ceiling. Pin so a bump to e.g. 30d surfaces in
    review — longer grace = longer leaked-secret window."""
    assert MAX_GRACE_SECONDS == 604800


def test_default_below_max():
    assert DEFAULT_GRACE_SECONDS < MAX_GRACE_SECONDS


# ---------- Current secret matches ----------


def test_current_matches_returns_current_label():
    valid, label = is_signature_valid_during_rotation(
        matches=_matches_only("CURRENT"),
        current_secret="CURRENT",
        previous_secret="PREVIOUS",
        rotated_at=ROTATED_AT,
        now=IN_GRACE,
    )
    assert valid is True
    assert label == "current"


def test_current_match_does_not_call_matches_on_previous():
    """Cardinal pin: when current matches, the previous secret
    is NEVER tested. Defends against an unnecessary HMAC compute
    on the happy path."""
    calls: list[str] = []
    is_signature_valid_during_rotation(
        matches=_matches_only("CURRENT", calls),
        current_secret="CURRENT",
        previous_secret="PREVIOUS",
        rotated_at=ROTATED_AT,
        now=IN_GRACE,
    )
    assert calls == ["CURRENT"]


# ---------- Previous secret in grace ----------


def test_previous_matches_in_grace_returns_previous_label():
    """Pin: when current fails but previous matches AND we're
    in grace, validate as previous."""
    valid, label = is_signature_valid_during_rotation(
        matches=_matches_only("PREVIOUS"),
        current_secret="CURRENT",
        previous_secret="PREVIOUS",
        rotated_at=ROTATED_AT,
        now=IN_GRACE,
    )
    assert valid is True
    assert label == "previous"


def test_previous_match_calls_matches_twice():
    """Cardinal pin: at most twice (current then previous).
    Pin observability — the caller may log call count."""
    calls: list[str] = []
    is_signature_valid_during_rotation(
        matches=_matches_only("PREVIOUS", calls),
        current_secret="CURRENT",
        previous_secret="PREVIOUS",
        rotated_at=ROTATED_AT,
        now=IN_GRACE,
    )
    assert calls == ["CURRENT", "PREVIOUS"]


# ---------- Previous secret out of grace ----------


def test_previous_matches_outside_grace_rejected():
    """Cardinal pin: outside grace, previous_secret is REJECTED
    even if it would otherwise match. A leaked previous-secret
    can't be used after grace expires."""
    valid, label = is_signature_valid_during_rotation(
        matches=_matches_only("PREVIOUS"),
        current_secret="CURRENT",
        previous_secret="PREVIOUS",
        rotated_at=ROTATED_AT,
        now=OUT_OF_GRACE,
    )
    assert valid is False
    assert label is None


def test_at_grace_boundary_is_out():
    """Strict `>=` boundary: `now == grace_end` is OUT of grace.
    Pin so a refactor to `>` would silently extend the grace by
    one tick."""
    valid, label = is_signature_valid_during_rotation(
        matches=_matches_only("PREVIOUS"),
        current_secret="CURRENT",
        previous_secret="PREVIOUS",
        rotated_at=ROTATED_AT,
        now=AT_GRACE_BOUNDARY,
    )
    assert valid is False
    assert label is None


def test_one_microsecond_before_boundary_in_grace():
    """Just-before-boundary still validates."""
    just_before = AT_GRACE_BOUNDARY - timedelta(microseconds=1)
    valid, label = is_signature_valid_during_rotation(
        matches=_matches_only("PREVIOUS"),
        current_secret="CURRENT",
        previous_secret="PREVIOUS",
        rotated_at=ROTATED_AT,
        now=just_before,
    )
    assert valid is True
    assert label == "previous"


# ---------- No previous secret ----------


def test_no_previous_secret_only_current_path():
    """previous_secret=None → no rotation in progress. Only
    current secret tried. matches called at most ONCE."""
    calls: list[str] = []
    valid, label = is_signature_valid_during_rotation(
        matches=_matches_only("PREVIOUS", calls),
        current_secret="CURRENT",
        previous_secret=None,
        rotated_at=ROTATED_AT,
        now=IN_GRACE,
    )
    assert valid is False
    assert label is None
    assert calls == ["CURRENT"]


def test_no_rotated_at_only_current_path():
    """Symmetric: rotated_at=None means no rotation, even if
    previous_secret is set."""
    calls: list[str] = []
    valid, _ = is_signature_valid_during_rotation(
        matches=_matches_only("PREVIOUS", calls),
        current_secret="CURRENT",
        previous_secret="PREVIOUS",
        rotated_at=None,
        now=IN_GRACE,
    )
    assert valid is False
    assert calls == ["CURRENT"]


# ---------- Neither matches ----------


def test_neither_matches_rejected():
    valid, label = is_signature_valid_during_rotation(
        matches=lambda _: False,
        current_secret="CURRENT",
        previous_secret="PREVIOUS",
        rotated_at=ROTATED_AT,
        now=IN_GRACE,
    )
    assert valid is False
    assert label is None


# ---------- Grace clamping ----------


def test_negative_grace_clamps_to_zero():
    """Negative grace → 0 → no grace window at all (anything
    after rotated_at is out)."""
    valid, _ = is_signature_valid_during_rotation(
        matches=_matches_only("PREVIOUS"),
        current_secret="CURRENT",
        previous_secret="PREVIOUS",
        rotated_at=ROTATED_AT,
        now=ROTATED_AT + timedelta(seconds=1),
        grace_seconds=-100,
    )
    assert valid is False


def test_above_max_grace_clamps_to_max():
    """grace_seconds=MAX*2 clamps to MAX. A request at MAX+1s
    is out; at MAX-1s is in."""
    valid_just_in, _ = is_signature_valid_during_rotation(
        matches=_matches_only("PREVIOUS"),
        current_secret="CURRENT",
        previous_secret="PREVIOUS",
        rotated_at=ROTATED_AT,
        now=ROTATED_AT + timedelta(seconds=MAX_GRACE_SECONDS - 1),
        grace_seconds=MAX_GRACE_SECONDS * 2,
    )
    assert valid_just_in is True

    valid_just_out, _ = is_signature_valid_during_rotation(
        matches=_matches_only("PREVIOUS"),
        current_secret="CURRENT",
        previous_secret="PREVIOUS",
        rotated_at=ROTATED_AT,
        now=ROTATED_AT + timedelta(seconds=MAX_GRACE_SECONDS + 1),
        grace_seconds=MAX_GRACE_SECONDS * 2,
    )
    assert valid_just_out is False


def test_zero_grace_means_no_window():
    """grace_seconds=0 → strict cutover (no grace at all)."""
    valid, _ = is_signature_valid_during_rotation(
        matches=_matches_only("PREVIOUS"),
        current_secret="CURRENT",
        previous_secret="PREVIOUS",
        rotated_at=ROTATED_AT,
        now=ROTATED_AT,  # exactly at rotation
        grace_seconds=0,
    )
    assert valid is False


# ---------- Custom grace ----------


def test_custom_grace_window():
    """Caller can pass explicit grace_seconds."""
    short_grace = 3600  # 1 hour
    in_short = ROTATED_AT + timedelta(minutes=30)
    out_short = ROTATED_AT + timedelta(hours=2)

    valid_in, _ = is_signature_valid_during_rotation(
        matches=_matches_only("PREVIOUS"),
        current_secret="CURRENT",
        previous_secret="PREVIOUS",
        rotated_at=ROTATED_AT,
        now=in_short,
        grace_seconds=short_grace,
    )
    assert valid_in is True

    valid_out, _ = is_signature_valid_during_rotation(
        matches=_matches_only("PREVIOUS"),
        current_secret="CURRENT",
        previous_secret="PREVIOUS",
        rotated_at=ROTATED_AT,
        now=out_short,
        grace_seconds=short_grace,
    )
    assert valid_out is False
