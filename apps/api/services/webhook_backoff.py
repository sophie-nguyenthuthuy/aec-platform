"""Webhook delivery backoff schedule (cycle Z1).

Today the backoff schedule lives inline in `services.webhooks` as
`_BACKOFF_MINUTES = [0, 1, 5, 30, 120, 720]` plus the per-row
arithmetic in `_schedule_retry` / `_mark_failed_permanently`. A
tweak (e.g. add a 4-day final attempt for partners with weekend
on-call rotations) currently means three edits across the
dispatcher module + a separate test file.

This module is the single source of truth.

Schedule: minutes from the FIRST attempt to each subsequent retry.

  attempt 0 → 0 min   (initial — fired by the cron tick)
  attempt 1 → 1 min   (recover from a transient receiver blip)
  attempt 2 → 5 min   (DNS / load-balancer rotation)
  attempt 3 → 30 min  (medium outage)
  attempt 4 → 2 hr    (longer outage; partner on-call notified)
  attempt 5 → 12 hr   (overnight retry; weekend deploy window)
  attempt 6 → terminal failure → row marked `failed`

Total wall-clock from first attempt to terminal failure:
  0 + 1 + 5 + 30 + 120 + 720 = 876 minutes ≈ 14.6 hours.

Why these specific values:
  * 1 / 5 / 30 minutes covers transient (DNS, deploy) → short
    outage. 90% of recoveries land in this window per Stripe's
    public webhook retry data.
  * 2h / 12h covers "your team's on-call paged" → "weekend
    rotation woke up." The 12h gap means a Friday night
    delivery surfaces by Saturday afternoon at worst.
  * 6 attempts total caps the retention pressure on
    `webhook_deliveries`: a never-recovering subscription's
    deliveries age into terminal-failed within 15 hours, then
    the 30d retention prune catches them.

Pure Python — no DB, no async. The dispatcher's existing
`_schedule_retry` is expected to delegate here in a follow-up.
"""

from __future__ import annotations

from datetime import datetime, timedelta

# Per-attempt delay in minutes. attempt N's retry fires N-th index
# minutes after the row's `created_at`.
#
# attempt 0 is special: it's the row's initial delivery (fired by
# the very first cron tick after enqueue), not a retry. Including 0
# in the array keeps the indexing self-explanatory:
# `BACKOFF_MINUTES[attempt_count]` always returns "minutes from
# created_at to the attempt that just failed."
BACKOFF_MINUTES: list[int] = [0, 1, 5, 30, 120, 720]


# Convenience: max retry-attempt index. After this many failures
# the row is terminal-failed.
MAX_ATTEMPTS = len(BACKOFF_MINUTES)


def next_retry_at(*, attempt_count: int, base_time: datetime) -> datetime | None:
    """Compute when the next retry should fire.

    `attempt_count` is the count of attempts ALREADY made (i.e. the
    failed-attempt count after the most-recent failure). The next
    attempt index is `attempt_count` itself; we look up its delay
    in `BACKOFF_MINUTES`.

    `base_time` is the row's `created_at` — schedule is anchored
    there (NOT to the most-recent attempt) so a slow retry
    accidentally pushed back doesn't compound into a 24h gap.

    Returns `None` when the schedule is exhausted (the row should
    be marked `failed` permanently, not re-queued).

    Examples:
      * After the initial attempt fails (attempt_count = 1) →
        retry at base_time + 1 minute.
      * After 5 attempts have failed (attempt_count = 5) → retry
        at base_time + 12 hours.
      * After 6 attempts have failed (attempt_count = 6) → None
        (terminal).
    """
    if attempt_count < 0 or attempt_count >= MAX_ATTEMPTS:
        return None
    delay = timedelta(minutes=BACKOFF_MINUTES[attempt_count])
    return base_time + delay


def is_terminal_failure(*, attempt_count: int) -> bool:
    """True iff the schedule is exhausted — the row should be
    marked `failed` rather than re-queued.

    `attempt_count` is the count of attempts ALREADY made. After
    `MAX_ATTEMPTS` failures we give up.

    Pin the function rather than letting callers compare against
    `len(BACKOFF_MINUTES)` directly — a refactor that bumps the
    schedule needs only one touch.
    """
    return attempt_count >= MAX_ATTEMPTS


def total_window_minutes() -> int:
    """Sum of all backoff delays — the wall-clock from first
    attempt to terminal failure.

    Useful for partner-facing docs ("we'll keep retrying for
    ~15 hours") and for retention math (delivery rows age into
    terminal-failed within this window, then the 30d retention
    prune catches them)."""
    return sum(BACKOFF_MINUTES)
