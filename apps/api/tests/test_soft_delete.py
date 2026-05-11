"""Soft-delete tombstone helper (cycle UU2).

Pinned seams:
  1. TOMBSTONE_RETENTION_DAYS = 90.
  2. MIN/MAX = 7 / 365.
  3. Override clamped to band (same EE1 pattern).
  4. Strict `<` boundary at threshold (retained at boundary).
  5. Cross-cycle: tombstone < audit retention.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from services.retention_policy import RETENTION_DAYS_DEFAULT
from services.soft_delete import (
    MAX_TOMBSTONE_DAYS,
    MIN_TOMBSTONE_DAYS,
    TOMBSTONE_RETENTION_DAYS,
    effective_tombstone_days,
    purge_threshold,
    should_hard_purge,
)

NOW = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)


# ---------- Constants ----------


def test_default_is_90_days():
    """3-month default. Pin against drop to e.g. 30 days."""
    assert TOMBSTONE_RETENTION_DAYS == 90


def test_min_is_7_days():
    """Floor — defends against 0-day typo immediately
    hard-purging on soft-delete."""
    assert MIN_TOMBSTONE_DAYS == 7


def test_max_is_365_days():
    assert MAX_TOMBSTONE_DAYS == 365


def test_band_ordering():
    assert MIN_TOMBSTONE_DAYS < TOMBSTONE_RETENTION_DAYS
    assert TOMBSTONE_RETENTION_DAYS < MAX_TOMBSTONE_DAYS


# ---------- effective_tombstone_days ----------


def test_none_override_returns_default():
    assert effective_tombstone_days(None) == TOMBSTONE_RETENTION_DAYS


def test_in_band_override_returned():
    assert effective_tombstone_days(30) == 30
    assert effective_tombstone_days(180) == 180


def test_zero_clamps_to_min():
    """Pin: typo defense — 0 → 7 (NOT immediate purge)."""
    assert effective_tombstone_days(0) == MIN_TOMBSTONE_DAYS


def test_negative_clamps_to_min():
    assert effective_tombstone_days(-5) == MIN_TOMBSTONE_DAYS


def test_above_max_clamps_down():
    assert effective_tombstone_days(1000) == MAX_TOMBSTONE_DAYS


def test_at_min_boundary():
    assert effective_tombstone_days(7) == 7


def test_at_max_boundary():
    assert effective_tombstone_days(365) == 365


# ---------- purge_threshold ----------


def test_purge_threshold_default_is_90_days_ago():
    assert purge_threshold(None, NOW) == NOW - timedelta(days=90)


def test_purge_threshold_with_override():
    assert purge_threshold(30, NOW) == NOW - timedelta(days=30)


def test_purge_threshold_uses_clamped():
    """Pin: misconfigured 0 → uses 7-day threshold, NOT 0."""
    assert purge_threshold(0, NOW) == NOW - timedelta(days=MIN_TOMBSTONE_DAYS)


# ---------- should_hard_purge ----------


def test_should_hard_purge_true_for_old_tombstone():
    """100-day-old soft-delete with default 90 → purge."""
    deleted = NOW - timedelta(days=100)
    assert should_hard_purge(deleted, None, NOW) is True


def test_should_hard_purge_false_for_recent():
    deleted = NOW - timedelta(days=30)
    assert should_hard_purge(deleted, None, NOW) is False


def test_should_hard_purge_false_at_threshold():
    """Cardinal boundary pin: row AT threshold is RETAINED.
    Strict `<` not `<=`. Defends against a row deleted exactly
    90 days ago getting surprise-purged."""
    at_threshold = NOW - timedelta(days=90)
    assert should_hard_purge(at_threshold, None, NOW) is False


def test_should_hard_purge_true_one_microsecond_past():
    past = NOW - timedelta(days=90, microseconds=1)
    assert should_hard_purge(past, None, NOW) is True


def test_should_hard_purge_uses_effective_bound():
    """Override=0 → clamps to 7 → 30-day-old row is preserved
    (not purged at the user's typo'd 0)."""
    deleted = NOW - timedelta(days=5)
    assert should_hard_purge(deleted, 0, NOW) is False


# ---------- Cross-cycle composition with EE1 ----------


def test_tombstone_retention_less_than_audit_default():
    """Cardinal cross-cycle pin: tombstone retention MUST be
    less than EE1's default audit retention. Otherwise an
    audit row referring to a soft-deleted resource could
    expire BEFORE the tombstone is hard-purged — leaving a
    dangling audit reference to a non-existent (but still
    soft-deleted) row.

    Pin so a refactor that bumps tombstone retention past
    audit retention surfaces here."""
    assert TOMBSTONE_RETENTION_DAYS < RETENTION_DAYS_DEFAULT


def test_max_tombstone_does_not_exceed_audit_default():
    """Even at MAX override (365 days), tombstone retention
    stays at-or-below audit default (also 365). Pin so a
    refactor that bumps MAX_TOMBSTONE doesn't accidentally
    exceed audit retention."""
    assert MAX_TOMBSTONE_DAYS <= RETENTION_DAYS_DEFAULT
