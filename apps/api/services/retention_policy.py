"""Audit retention policy resolver (cycle EE1).

Given an org's retention override + an audit row's `created_at`,
return whether to retain or purge at `now`. Today the daily
prune cron has the policy logic inline; the admin retention-
override audit emit duplicates the resolved-bound calculation;
a future "retention coverage" report will need a third copy.
This module is the single source of truth.

  RETENTION_DAYS_DEFAULT      — 365 (one year, sensible default)
  RETENTION_DAYS_MIN          — 30  (legal "we still have it" floor)
  RETENTION_DAYS_MAX          — 2555 (~7 years, legal ceiling)
  OrgRetentionSettings        — frozen: retention_days_override
  effective_retention_days(s) — int, clamped to [MIN, MAX]
  purge_threshold(s, now)     — datetime cutoff
  should_purge(created, s, n) — bool

Override clamping rules (pinned by tests):
  * `override is None` → DEFAULT (NOT MIN — pin against a refactor
    that treats absent override as "minimum retention").
  * `override < MIN` → clamps UP to MIN. Defends against a
    misconfigured org silently losing too-recent audit history
    (e.g. an admin types `7` thinking days but means weeks; the
    floor catches the typo).
  * `override > MAX` → clamps DOWN to MAX. Legal ceiling — past
    7 years the data is operationally noise and storage cost.
  * `override` in `[MIN, MAX]` → returned verbatim.

Pure stdlib.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

# Sensible default for orgs that haven't configured an override.
# 365 days = one year, matches the default retention covenant in
# the standard ToS. Pin so a refactor that drops to e.g. 90 days
# silently shortens audit history for every untouched org.
RETENTION_DAYS_DEFAULT = 365


# Legal floor — orgs cannot drop retention below 30 days. Even
# an aggressively configured org must keep a month of audit trail.
RETENTION_DAYS_MIN = 30


# Legal ceiling — 7 years matches Vietnamese tax record retention
# law. Past this, the data is operationally noise and storage cost.
# Pin via test so a refactor that bumps to e.g. 10 years (which
# would push some orgs past their data-residency commitment)
# surfaces in review.
RETENTION_DAYS_MAX = 2555


@dataclass(frozen=True)
class OrgRetentionSettings:
    """Org retention configuration snapshot.

    `retention_days_override`:
      * `None` — use RETENTION_DAYS_DEFAULT.
      * `int` — clamped into `[RETENTION_DAYS_MIN, RETENTION_DAYS_MAX]`.
    """

    retention_days_override: int | None


def effective_retention_days(settings: OrgRetentionSettings) -> int:
    """Resolve the effective retention bound in days.

    See module docstring for clamping rules.
    """
    n = settings.retention_days_override
    if n is None:
        return RETENTION_DAYS_DEFAULT
    if n < RETENTION_DAYS_MIN:
        return RETENTION_DAYS_MIN
    if n > RETENTION_DAYS_MAX:
        return RETENTION_DAYS_MAX
    return n


def purge_threshold(settings: OrgRetentionSettings, now: datetime) -> datetime:
    """Return the cutoff datetime: rows with `created_at` STRICTLY
    older than this should be purged.

    A row at exactly the threshold is retained (strict `<` in
    `should_purge`). Pin so a row created exactly N days ago
    isn't surprise-purged at the boundary.
    """
    days = effective_retention_days(settings)
    return now - timedelta(days=days)


def should_purge(
    created_at: datetime,
    settings: OrgRetentionSettings,
    now: datetime,
) -> bool:
    """True iff `created_at` is older than the resolved retention
    bound.

    Boundary: rows AT the threshold are retained (strict `<`).
    Defensive: caller is responsible for tz-awareness consistency
    between `created_at` and `now` — mismatched datetimes raise
    TypeError, which is the right posture (the prune cron should
    crash visibly on a bug, not silently mis-purge).
    """
    return created_at < purge_threshold(settings, now)
