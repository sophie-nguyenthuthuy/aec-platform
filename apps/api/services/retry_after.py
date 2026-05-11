"""Webhook Retry-After header parser (cycle FF2).

Parses HTTP `Retry-After` per RFC 7231 §7.1.3 in two forms:
  * Integer delta-seconds: `Retry-After: 60`
  * HTTP-date:             `Retry-After: Wed, 21 Oct 2026 07:28:00 GMT`

Returns canonical seconds-from-`now` or None.

Composes with `services.webhook_backoff` (Z1):

    retry_after = parse_retry_after(response.headers.get("retry-after"), now)
    backoff = next_retry_at(attempt_count, base_time)
    # Honor server backpressure when it asks for longer than our default.
    sleep_seconds = max(retry_after or 0, backoff_seconds)

  parse_retry_after(header_value, now)  — int seconds or None
  MAX_RETRY_AFTER_SECONDS               — 3600 (1-hour cap)

Defenses:
  * Cap at MAX_RETRY_AFTER_SECONDS (1 hour). Without a cap, a
    buggy server returning `Retry-After: 86400` would park the
    delivery queue for a day.
  * HTTP-date in the past → 0 (deliver now, don't sleep). A
    misconfigured server clock shouldn't park the queue.
  * Negative integer → None (RFC 7231 says non-negative). The
    caller falls back to the Z1 default backoff.
  * Malformed → None.

Pure stdlib (uses `email.utils.parsedate_to_datetime` for the
HTTP-date form, which RFC 7231 references via RFC 5322 / RFC 1123).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

# Cap on the parsed value. Defends against a buggy upstream
# returning a multi-day Retry-After. 1 hour is generous enough
# for legitimate rate-limited downstreams while bounding
# damage from misconfigured ones.
MAX_RETRY_AFTER_SECONDS = 3600


_INT_RE = re.compile(r"^\d+$")


def parse_retry_after(
    header_value: str | None,
    now: datetime,
) -> int | None:
    """Parse the Retry-After header value to seconds-from-`now`.

    Returns:
      * `int` in [0, MAX_RETRY_AFTER_SECONDS] for a valid header.
      * `None` for None / empty / malformed input.

    `now` must be tz-aware if the header is in HTTP-date form.
    Naive HTTP-dates are interpreted as UTC (per RFC 7231).
    """
    if header_value is None:
        return None
    s = header_value.strip()
    if not s:
        return None

    # Form 1: integer delta-seconds. The regex anchors and
    # forbids leading sign / whitespace inside, so "-1" or
    # "60s" both fall through to the HTTP-date branch (and
    # fail there) rather than being silently accepted.
    if _INT_RE.match(s):
        n = int(s)
        return min(n, MAX_RETRY_AFTER_SECONDS)

    # Form 2: HTTP-date (RFC 1123 / 5322).
    try:
        dt = parsedate_to_datetime(s)
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None

    # Naive datetime → assume UTC per RFC 7231.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)

    delta = (dt - now).total_seconds()
    if delta < 0:
        # Past date — deliver now, don't sleep. A misconfigured
        # server clock shouldn't park the queue.
        return 0
    return min(int(delta), MAX_RETRY_AFTER_SECONDS)
