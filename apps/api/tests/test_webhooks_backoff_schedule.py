"""Pin the webhook dispatcher's retry / failure constants.

These four values shape every customer integration's experience when
their webhook receiver flakes:

  * `_BACKOFF_MINUTES` — schedule from creation to each attempt. A
    typo here silently changes retry timing for every receiver. The
    exact values were tuned to give a flaky receiver ~14 hours of
    automatic recovery before the delivery is marked permanently
    failed (and surfaced in the dead-letter dashboard).

  * `_DISABLE_AFTER_FAILURES` — auto-disable a subscription after
    this many consecutive failures so we don't hammer a dead URL
    forever. Counter resets on success.

  * `_HTTP_TIMEOUT_SEC` — per-attempt HTTP timeout. MUST be tighter
    than the cron interval (60s) so a stuck delivery doesn't pile
    up alongside its retries.

  * `_MAX_RESPONSE_SNIPPET` — cap on stored response bodies. Keeps a
    chatty receiver from bloating the deliveries table.

A test that pins these by name is the cheapest insurance against a
refactor that "tightens the timing" + accidentally drops the 12h
final retry, or "simplifies" the disable threshold to 5 (way too
trigger-happy) without realising the customer-impact blast radius.

If you intentionally change one of these values, update this test
in the same PR — that's the explicit signal that the change is a
behaviour-shift, not a typo.
"""

from __future__ import annotations

from services.webhooks import (
    _BACKOFF_MINUTES,
    _DISABLE_AFTER_FAILURES,
    _HTTP_TIMEOUT_SEC,
    _MAX_RESPONSE_SNIPPET,
)


def test_backoff_minutes_exact_schedule():
    """Pin the exact 6-attempt schedule from creation to each retry.

    Total span: 0 + 1 + 5 + 30 + 120 + 720 = 876 minutes ≈ 14.6 hours.
    A receiver that's down for a deploy window (typically <2h) recovers
    inside the schedule; one that's down for >14h surfaces in dead-letter.
    """
    assert _BACKOFF_MINUTES == [0, 1, 5, 30, 120, 720]


def test_backoff_attempt_count_implied():
    """The schedule length IS the attempt count. Six attempts means a
    delivery transitions to permanent `failed` after the 6th try fails.
    Adding a 7th entry would extend the dead-letter delay; removing
    one would shrink it. Either way, the dispatcher's
    `attempt >= len(_BACKOFF_MINUTES)` branch is the canonical end-of-
    line check, so this test guards the count semantically rather
    than hard-coding `== 6` separately."""
    assert len(_BACKOFF_MINUTES) == 6


def test_backoff_is_monotonically_non_decreasing():
    """Each retry must be at least as far out as the previous one.

    A regression that flipped two entries (e.g. `[0, 5, 1, 30, …]`)
    would cause delivery #3 to fire BEFORE delivery #2's retry slot
    and create cron-tick races. Pin the invariant explicitly so a
    reorder is caught even if the new schedule's total span is
    coincidentally similar.
    """
    # `strict=False` because `a[1:]` is by design shorter by one —
    # the iteration covers adjacent pairs (i, i+1) for i in 0..n-2.
    for prev, nxt in zip(_BACKOFF_MINUTES, _BACKOFF_MINUTES[1:], strict=False):
        assert nxt >= prev, f"backoff went backwards: {prev} → {nxt}"


def test_backoff_first_attempt_is_immediate():
    """Attempt 0 (the initial delivery) MUST fire immediately —
    `next_retry_at = NOW() + 0 minutes` so the next cron tick picks
    it up. A non-zero first entry would silently delay every
    delivery's first attempt by that many minutes. Customers would
    see "you said the webhook fired but I got nothing for 5 minutes."
    """
    assert _BACKOFF_MINUTES[0] == 0


def test_disable_after_failures_threshold():
    """Twenty consecutive failures before auto-disable.

    Tuning rationale: a receiver that's down for one deploy window
    (~2h) might generate 2-3 delivery failures (one initial + retries).
    A threshold of 20 means it would take ~ten consecutive deploy
    failures or a ~2-day outage before the subscription auto-
    disables. That's intentionally conservative — auto-disabling is
    customer-disruptive (their integration silently stops working)
    so we'd rather burn cron cycles on a known-dead URL than disable
    a subscription that's about to come back up.
    """
    assert _DISABLE_AFTER_FAILURES == 20


def test_http_timeout_is_tighter_than_cron_interval():
    """The per-attempt HTTP timeout must be tighter than the cron's
    one-minute tick — otherwise a single stuck delivery could wedge
    the worker past the next tick + cause overlapping drains.

    10 seconds gives generous receivers plenty of headroom while
    bounding the worst case to a small fraction of the cron interval.
    The relationship is what matters; the exact 10s is the chosen
    point on that curve.
    """
    assert _HTTP_TIMEOUT_SEC < 60.0
    # Also pin the exact value so a "let's bump it to 30" change has
    # to update the test — that change has real implications (it
    # extends the worst-case worker wedge from 10s to 30s).
    assert _HTTP_TIMEOUT_SEC == 10.0


def test_response_snippet_cap_prevents_table_bloat():
    """Cap response bodies at 500 chars. A receiver that returns
    kilobytes of HTML on every error (Vercel does this) would
    otherwise inflate `webhook_deliveries.response_body_snippet`
    indefinitely. 500 is enough to capture a stack trace's first
    line + a few error fields; bigger contributes nothing to debug
    value.
    """
    assert _MAX_RESPONSE_SNIPPET == 500
