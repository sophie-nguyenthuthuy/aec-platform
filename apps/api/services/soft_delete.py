"""Soft-delete tombstone helper (cycle UU2).

Determine when a soft-deleted row should be hard-purged.
Tombstone retention is INDEPENDENT of audit retention (EE1):

  * Audit rows referring to the deleted resource may stick
    around (per EE1 retention) AFTER the resource itself is
    hard-purged.
  * Tombstone (soft-delete) retention is the operational
    "oops, undelete" window — short enough to fit RAM-cache
    reasonable, long enough that legitimate "I deleted it
    yesterday, give me back" works.

  effective_tombstone_days(override)        — int, clamped
  purge_threshold(override, now)            — datetime cutoff
  should_hard_purge(deleted_at, ...)        — bool
  TOMBSTONE_RETENTION_DAYS                  — 90 (default)
  MIN_TOMBSTONE_DAYS / MAX_TOMBSTONE_DAYS   — 7 / 365

Composes with EE1's `RETENTION_DAYS_DEFAULT` for the cross-cycle
invariant `TOMBSTONE_RETENTION_DAYS < RETENTION_DAYS_DEFAULT` —
audit trail outlives the soft-delete window so historical
audit refs don't dangle to non-existent rows.

Pinned invariants:
  * Default 90 days (3 months — common "oops" window).
  * Override clamped to `[MIN, MAX]` (same EE1 pattern).
  * Strict `<` boundary: row at exactly threshold is RETAINED.
  * Cross-cycle: tombstone retention < audit retention.

Pure stdlib + EE1.
"""

from __future__ import annotations

from datetime import datetime, timedelta

# Default tombstone retention. 90 days = 3 months. Pin against
# a refactor that drops to e.g. 30 days (which would silently
# shorten the "oops, undelete" window for every untouched org).
TOMBSTONE_RETENTION_DAYS = 90


# Floor — even an aggressively-configured org keeps a week
# of soft-delete grace. Defends against a `0` typo that would
# hard-purge immediately on soft-delete.
MIN_TOMBSTONE_DAYS = 7


# Ceiling — past 1 year, the tombstone is operationally a
# different concept (cold storage). Pin against a bump that
# would push past audit retention.
MAX_TOMBSTONE_DAYS = 365


def effective_tombstone_days(override: int | None) -> int:
    """Resolve the effective tombstone retention bound.

    Override clamping rules (mirror EE1's pattern):
      * `override is None` → DEFAULT.
      * `override < MIN` → clamps UP to MIN.
      * `override > MAX` → clamps DOWN to MAX.
      * `override` in `[MIN, MAX]` → returned verbatim.
    """
    if override is None:
        return TOMBSTONE_RETENTION_DAYS
    if override < MIN_TOMBSTONE_DAYS:
        return MIN_TOMBSTONE_DAYS
    if override > MAX_TOMBSTONE_DAYS:
        return MAX_TOMBSTONE_DAYS
    return override


def purge_threshold(
    override: int | None,
    now: datetime,
) -> datetime:
    """Return the cutoff datetime for hard-purge.

    Rows with `deleted_at` STRICTLY older than this should be
    hard-purged. Boundary defense (strict `<`) means a row at
    exactly the threshold is RETAINED.
    """
    days = effective_tombstone_days(override)
    return now - timedelta(days=days)


def should_hard_purge(
    deleted_at: datetime,
    override: int | None,
    now: datetime,
) -> bool:
    """True iff `deleted_at` is older than the tombstone retention.

    Boundary: rows AT the threshold are retained (strict `<`).
    """
    return deleted_at < purge_threshold(override, now)
