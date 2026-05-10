"""HTTP status code → severity tone mapper (cycle EE3, Python half).

Server-side mirror of `apps/web/lib/http-status-tone.ts`. Used by:

  * The webhook delivery CSV / pinned-export tone-suffix column.
  * The Slack alert digest tone selector (the failure card uses
    a different background tint depending on whether the failed
    delivery was a 4xx or 5xx).
  * The audit row plaintext export's status-class label.

  classify_status(code)  — StatusTone(severity, tone)
  SEVERITIES             — closed severity tuple
  TONES                  — closed Tailwind tone tuple (parallel)

Pure stdlib.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Severity = Literal["success", "redirect", "client_error", "server_error", "unknown"]
Tone = Literal["emerald", "sky", "amber", "rose", "zinc"]


# Closed severity tuple. Order matches TONES so the index
# positions parallel. Pin via test.
SEVERITIES: tuple[Severity, ...] = (
    "success",
    "redirect",
    "client_error",
    "server_error",
    "unknown",
)


# Closed tone tuple. Tailwind-compatible color names — pin so a
# refactor that swaps to a Tailwind-incompatible tone (e.g.
# "danger") would break every consuming component's class
# generation.
TONES: tuple[Tone, ...] = ("emerald", "sky", "amber", "rose", "zinc")


@dataclass(frozen=True)
class StatusTone:
    severity: Severity
    tone: Tone


_UNKNOWN = StatusTone(severity="unknown", tone="zinc")


def classify_status(code: int | None) -> StatusTone:
    """Classify an HTTP status code into a severity bucket + tone.

      * 2xx → StatusTone(success, emerald)
      * 3xx → StatusTone(redirect, sky)
      * 4xx → StatusTone(client_error, amber)   ← 408, 429 are HERE
      * 5xx → StatusTone(server_error, rose)
      * 1xx / 6xx+ / None / non-int → StatusTone(unknown, zinc)

    408 (Request Timeout) and 429 (Too Many Requests) are
    client_error per the spec — they signal the client is at
    fault (took too long, sent too many requests). Pin so a
    "treat 408 as server_error because the connection died"
    shortcut doesn't slip in.
    """
    if code is None:
        return _UNKNOWN
    try:
        c = int(code)
    except (TypeError, ValueError):
        return _UNKNOWN
    if 200 <= c < 300:
        return StatusTone(severity="success", tone="emerald")
    if 300 <= c < 400:
        return StatusTone(severity="redirect", tone="sky")
    if 400 <= c < 500:
        return StatusTone(severity="client_error", tone="amber")
    if 500 <= c < 600:
        return StatusTone(severity="server_error", tone="rose")
    return _UNKNOWN
