"""Audit retention policy resolver (cycle EE1).

Pinned seams:
  1. RETENTION_DAYS_DEFAULT = 365.
  2. RETENTION_DAYS_MIN = 30.
  3. RETENTION_DAYS_MAX = 2555 (~7 years).
  4. override=None → DEFAULT (NOT MIN).
  5. override < MIN → clamps UP to MIN (typo defense).
  6. override > MAX → clamps DOWN to MAX (legal ceiling).
  7. should_purge boundary: row AT threshold is retained (strict <).
  8. OrgRetentionSettings is frozen.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from services.retention_policy import (
    RETENTION_DAYS_DEFAULT,
    RETENTION_DAYS_MAX,
    RETENTION_DAYS_MIN,
    OrgRetentionSettings,
    effective_retention_days,
    purge_threshold,
    should_purge,
)

NOW = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)


# ---------- Constants ----------


def test_retention_days_default_is_one_year():
    assert RETENTION_DAYS_DEFAULT == 365


def test_retention_days_min_is_thirty():
    """30 days is the legal "we still have it" floor — even an
    aggressively configured org keeps a month of audit trail."""
    assert RETENTION_DAYS_MIN == 30


def test_retention_days_max_is_seven_years():
    """2555 days ≈ 7 years matches VN tax record retention law.
    Pin so a bump (e.g. to 10 years) surfaces in review — some
    orgs have data-residency commitments that depend on this
    ceiling."""
    assert RETENTION_DAYS_MAX == 2555


def test_min_below_default():
    """MIN < DEFAULT < MAX — pin the band ordering."""
    assert RETENTION_DAYS_MIN < RETENTION_DAYS_DEFAULT
    assert RETENTION_DAYS_DEFAULT < RETENTION_DAYS_MAX


# ---------- effective_retention_days ----------


def test_effective_none_override_returns_default():
    """Cardinal pin: absent override falls back to DEFAULT, NOT
    MIN. A refactor that treats `None` as "minimum retention"
    would silently shorten audit history for every org that
    hasn't explicitly configured an override."""
    settings = OrgRetentionSettings(retention_days_override=None)
    assert effective_retention_days(settings) == RETENTION_DAYS_DEFAULT


def test_effective_in_band_override_returned_verbatim():
    settings = OrgRetentionSettings(retention_days_override=90)
    assert effective_retention_days(settings) == 90


def test_effective_below_min_clamps_up():
    """Pin: override below MIN clamps UP to MIN. Typo defense —
    an admin who types `7` thinking days but means weeks would
    otherwise lose 23 days of audit history. The floor catches
    the typo and surfaces nothing alarming."""
    settings = OrgRetentionSettings(retention_days_override=7)
    assert effective_retention_days(settings) == RETENTION_DAYS_MIN


def test_effective_zero_override_clamps_to_min():
    settings = OrgRetentionSettings(retention_days_override=0)
    assert effective_retention_days(settings) == RETENTION_DAYS_MIN


def test_effective_negative_override_clamps_to_min():
    """Negative override is a misconfig — clamp UP rather than
    treat as "purge everything always"."""
    settings = OrgRetentionSettings(retention_days_override=-30)
    assert effective_retention_days(settings) == RETENTION_DAYS_MIN


def test_effective_above_max_clamps_down():
    """Pin: override above MAX clamps DOWN to MAX. Legal ceiling
    — past 7 years the data is operationally noise and storage
    cost; an admin asking for 100 years gets the legal max."""
    settings = OrgRetentionSettings(retention_days_override=10000)
    assert effective_retention_days(settings) == RETENTION_DAYS_MAX


def test_effective_at_min_boundary():
    settings = OrgRetentionSettings(retention_days_override=RETENTION_DAYS_MIN)
    assert effective_retention_days(settings) == RETENTION_DAYS_MIN


def test_effective_at_max_boundary():
    settings = OrgRetentionSettings(retention_days_override=RETENTION_DAYS_MAX)
    assert effective_retention_days(settings) == RETENTION_DAYS_MAX


# ---------- purge_threshold ----------


def test_purge_threshold_default_is_one_year_ago():
    settings = OrgRetentionSettings(retention_days_override=None)
    threshold = purge_threshold(settings, NOW)
    assert threshold == NOW - timedelta(days=365)


def test_purge_threshold_with_override():
    settings = OrgRetentionSettings(retention_days_override=90)
    threshold = purge_threshold(settings, NOW)
    assert threshold == NOW - timedelta(days=90)


def test_purge_threshold_clamped_override():
    """Threshold uses the clamped effective bound, not the raw
    override. Pin so a misconfigured 7-day override gets a
    30-day-old threshold (not a 7-day-old one)."""
    settings = OrgRetentionSettings(retention_days_override=7)
    threshold = purge_threshold(settings, NOW)
    assert threshold == NOW - timedelta(days=RETENTION_DAYS_MIN)


# ---------- should_purge ----------


def test_should_purge_true_for_old_row():
    """Row created 400 days ago, default retention 365 → purge."""
    settings = OrgRetentionSettings(retention_days_override=None)
    old_row = NOW - timedelta(days=400)
    assert should_purge(old_row, settings, NOW) is True


def test_should_purge_false_for_recent_row():
    settings = OrgRetentionSettings(retention_days_override=None)
    recent = NOW - timedelta(days=100)
    assert should_purge(recent, settings, NOW) is False


def test_should_purge_false_at_exact_threshold():
    """Boundary pin: a row at exactly N days old is RETAINED
    (strict `<` not `<=`). Defends against a row created
    "exactly N days ago to the second" being surprise-purged."""
    settings = OrgRetentionSettings(retention_days_override=None)
    at_threshold = NOW - timedelta(days=365)
    assert should_purge(at_threshold, settings, NOW) is False


def test_should_purge_true_one_microsecond_past_threshold():
    """One microsecond past → purge. Pin the boundary direction."""
    settings = OrgRetentionSettings(retention_days_override=None)
    past = NOW - timedelta(days=365, microseconds=1)
    assert should_purge(past, settings, NOW) is True


def test_should_purge_uses_effective_bound_not_raw_override():
    """A misconfigured 7-day override should use the clamped 30
    days, NOT 7. Pin so a row 20 days old isn't surprise-purged
    by a typo'd override."""
    settings = OrgRetentionSettings(retention_days_override=7)
    twenty_days_old = NOW - timedelta(days=20)
    assert should_purge(twenty_days_old, settings, NOW) is False


# ---------- OrgRetentionSettings shape ----------


def test_settings_is_frozen():
    """Pin so a refactor can't mutate settings in-place mid-loop
    in the prune cron."""
    settings = OrgRetentionSettings(retention_days_override=90)
    try:
        settings.retention_days_override = 30  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("OrgRetentionSettings should be frozen")
