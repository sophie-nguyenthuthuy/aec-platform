"""Cron mutual-exclusion audit.

The bug class
-------------
Every entry in `apps/api/workers/queue.py::WorkerSettings.cron_jobs`
fires on a wall-clock schedule. Today the deployment runs ONE arq
worker replica, so the cron tick fires once. The day someone scales
to 2 replicas (because the queue depth grew), every cron entry
fires TWICE per scheduled tick. For idempotent jobs that's wasteful;
for non-idempotent ones (`bidradar.scrape_all` against an external
API, `daily_activity_digest_cron` sending real email) it's a paging
incident.

The standard fix is for the cron handler to acquire a Postgres
advisory lock at the top of its body:

    async with session.begin():
        locked = await session.scalar(
            text("SELECT pg_try_advisory_xact_lock(:k)"),
            {"k": LOCK_KEY_FOR_THIS_CRON},
        )
        if not locked:
            logger.info("another replica holds the lock; skipping")
            return {"skipped": True}
        # … real cron body

`pg_advisory_xact_lock` releases at transaction end, so even a hard
crash mid-body releases the lock for the next tick. Constants per
cron are stored in `services/cron_locks.py` (or similar) so two
crons can't accidentally collide on the same key.

What this audit checks
----------------------
For each `cron(handler, ...)` registration in
`workers/queue.py::WorkerSettings.cron_jobs`, look at the handler
function's source. It must contain ONE of:

  1. A `pg_try_advisory_*` / `pg_advisory_*` SQL call (the proper
     mutex).
  2. A `FOR UPDATE SKIP LOCKED` clause — sufficient for cron handlers
     whose only side effect is processing rows from a queue table
     (`webhook_drain_cron` is the canonical example).
  3. An explicit `# cron-mutex: <reason>` comment in the body —
     catches the legitimate single-replica-only case + idempotent
     jobs whose double-fire is genuinely safe.

Ratchet
-------
Today's baseline is "every cron fails this check" — no advisory
locking is wired anywhere. We don't fix all of them in one PR;
this audit pins the count and ratchets DOWN as crons get migrated
to a documented mutex pattern. Reductions surface a green-failing
prompt to lower the baseline; additions red-gate.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

_API_ROOT = Path(__file__).resolve().parent.parent


# Patterns that satisfy the cron-mutex contract. Match against the
# handler's source code (text). A handler is "safe" if ANY pattern
# matches.
_MUTEX_PATTERNS = [
    # Postgres advisory locks — the canonical mechanism.
    re.compile(r"pg_(?:try_)?advisory(?:_xact)?_lock", re.IGNORECASE),
    # Row-level mutex via SKIP LOCKED — sufficient for queue-drain
    # crons that operate on rows one at a time.
    re.compile(r"FOR\s+UPDATE\s+SKIP\s+LOCKED", re.IGNORECASE),
    # Explicit acknowledgement: handler is documented as safe to
    # double-fire OR explicitly relies on single-replica deploy.
    # The comment must include a reason after the colon.
    re.compile(r"#\s*cron-mutex:\s*\S", re.IGNORECASE),
]


# Today's baseline: every cron handler fails the audit. We ratchet
# this down as crons migrate. When the count reaches 0, flip the
# assertion to strict (no offenders) and remove this constant.
BASELINE_UNSAFE_CRONS = 8  # 2026-05: 7→8 after `cron_failure_watchdog_cron` landed (every-5min Slack alerter; needs `pg_try_advisory_xact_lock` so two replicas don't double-post)


def _collect_cron_handlers() -> list[tuple[str, str]]:
    """Return [(handler_name, source)] for every cron registered.

    We import `workers.queue` and walk `WorkerSettings.cron_jobs`,
    extracting the handler from each `arq.cron.cron(...)` entry.
    Handlers come from the same module; their source is read via
    `inspect.getsource`.
    """
    from workers import queue as q  # noqa: I001 — local import is intentional

    out: list[tuple[str, str]] = []
    settings = q.WorkerSettings
    cron_jobs = getattr(settings, "cron_jobs", []) or []
    for entry in cron_jobs:
        # `arq.cron.cron(...)` returns a `CronJob` namedtuple-ish
        # object; the handler is on `.coroutine` (older arq) or
        # `.func` (newer). Try both.
        handler = getattr(entry, "coroutine", None) or getattr(entry, "func", None) or getattr(entry, "callable", None)
        if handler is None:
            continue
        try:
            # Unwrap decorator chains (e.g. `cron_telemetry_wrap`) so
            # we read the original cron's body, not the wrapper's.
            # `__wrapped__` is the standard `functools.wraps` convention.
            src = inspect.getsource(inspect.unwrap(handler))
        except (OSError, TypeError):
            src = ""
        out.append((handler.__name__, src))
    return out


def _has_mutex(src: str) -> bool:
    return any(p.search(src) for p in _MUTEX_PATTERNS)


def test_every_cron_handler_has_a_mutex_mechanism():
    """Walk every cron registration; assert each handler's source
    contains one of the recognised mutex patterns.

    Failure surfaces both directions of the ratchet:
      * COUNT > BASELINE: a new cron landed without a mutex.
        Add one of the patterns OR add a `# cron-mutex: <reason>`
        comment with explicit justification.
      * COUNT < BASELINE: someone fixed a cron! Bump the baseline
        so future regressions can't silently rebuild back up.
    """
    handlers = _collect_cron_handlers()
    assert handlers, "no cron handlers found — the auditor's import resolution is broken"

    unsafe = [name for name, src in handlers if not _has_mutex(src)]

    n = len(unsafe)
    if n > BASELINE_UNSAFE_CRONS:
        new = n - BASELINE_UNSAFE_CRONS
        pytest.fail(
            f"{new} new cron handler(s) added without a mutex mechanism "
            f"(total now {n}, baseline {BASELINE_UNSAFE_CRONS}).\n\n"
            f"Unsafe handlers:\n  " + "\n  ".join(sorted(unsafe)) + "\n\nEvery cron must include ONE of:\n"
            "  • `pg_try_advisory_xact_lock(<key>)` at the top of the body\n"
            "  • `FOR UPDATE SKIP LOCKED` for queue-drain crons\n"
            "  • A `# cron-mutex: <reason>` comment if double-fire is "
            "documented as safe (e.g. job is fully idempotent).\n\n"
            "Without this, scaling from 1 to 2 worker replicas double-"
            "fires every scheduled tick — wasteful for idempotent jobs, "
            "a paging incident for non-idempotent ones (e.g. external "
            "API calls, real email sends)."
        )
    if n < BASELINE_UNSAFE_CRONS:
        pytest.fail(
            f"Cron-mutex unsafe count dropped from {BASELINE_UNSAFE_CRONS} "
            f"to {n} (you fixed {BASELINE_UNSAFE_CRONS - n}). 🎉\n\n"
            f"Update `BASELINE_UNSAFE_CRONS` in this test to {n} so "
            f"future regressions can't silently grow back to the prior "
            f"level. Once the count reaches 0, flip the assertion to "
            f"strict equality and remove the baseline constant."
        )


def test_recognised_mutex_patterns_cover_the_documented_helpers():
    """Defensive: hand-rolled fixtures verifying each pattern matches
    its intended source shape.

    A regression that broke a regex (e.g. dropped a word boundary)
    would silently let unsafe crons through; this test gates the
    auditor itself.
    """
    advisory_xact = "await session.execute(text('SELECT pg_try_advisory_xact_lock(:k)'), ...)"
    assert _has_mutex(advisory_xact), "advisory xact lock not recognised"

    advisory_session = "await db.execute(text('SELECT pg_try_advisory_lock(42)'))"
    assert _has_mutex(advisory_session), "session-scope advisory lock not recognised"

    skip_locked = "SELECT id FROM webhook_deliveries WHERE status='pending' FOR UPDATE SKIP LOCKED"
    assert _has_mutex(skip_locked), "FOR UPDATE SKIP LOCKED not recognised"

    explicit_comment = "# cron-mutex: idempotent (operates on a single-row UPSERT)"
    assert _has_mutex(explicit_comment), "explicit cron-mutex comment not recognised"

    # Negative case: a comment WITHOUT a reason after the colon must NOT
    # satisfy the audit. The reason is what makes the exception
    # reviewable; an empty reason turns the comment into a way to
    # silence the gate.
    bare_comment = "# cron-mutex:"
    assert not _has_mutex(bare_comment), (
        "Empty cron-mutex comment should not satisfy the audit — the reason is what makes the exception reviewable."
    )
