"""Time-window helpers (cycle Z3, Python half).

Server-side mirror of `apps/web/lib/time-window.ts`. Same chip
definitions + parser bounds so the API and frontend agree on what
"24h" / "7d" / "30d" / "all time" mean.

Today the Query(le=365) bound is duplicated across multiple
endpoints (audit list, audit CSV, project audit, dead-letter,
deliveries listing). This module centralises:

  * `TIME_WINDOW_OPTIONS` — the canonical chip list (mirrors the
    TS constant; useful for openapi-doc rendering + future admin
    config UI).
  * `parse_since_days(value)` — validator with `[1, 365]` bounds.
  * `format_relative_age_vn(then, now)` — Vietnamese-first relative
    age string (used by Slack alert digests, email digests,
    audit row plaintext export).

Pure Python — no DB, no async. Drop-in for any handler / formatter.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

# Server-side cap on `since_days`. Mirrors `MAX_SINCE_DAYS` in
# `apps/web/lib/time-window.ts`. A hand-edited URL with
# `since_days=10000` clamps via `parse_since_days`.
MAX_SINCE_DAYS = 365


# Default chip when a page first loads. Cumulative S2/V3 ops
# dashboards converged on "last 7 days" — pin so a refactor doesn't
# silently shift to a wider default that hammers the audit query.
DEFAULT_SINCE_DAYS: int | None = 7


@dataclass(frozen=True)
class TimeWindowOption:
    """One chip in the time-window picker. Same field shape as the
    TS interface for cross-language consistency."""

    value: int | None  # days; None = "all time" sentinel
    label: str  # vi-VN UI label


# Canonical chip set. Order matters — chips render left-to-right
# in this exact sequence so a user moving between pages sees the
# same layout. Mirror of `apps/web/lib/time-window.ts::TIME_WINDOW_OPTIONS`.
TIME_WINDOW_OPTIONS: tuple[TimeWindowOption, ...] = (
    TimeWindowOption(value=1, label="24h"),
    TimeWindowOption(value=7, label="7d"),
    TimeWindowOption(value=30, label="30d"),
    TimeWindowOption(value=None, label="Tất cả"),
)


def parse_since_days(value: object) -> int | None:
    """Validate / coerce a since_days input from a request param.

    Three accepted forms:
      * None / "" → None (the "all time" sentinel).
      * int / numeric string within [1, MAX_SINCE_DAYS] → that int.
      * Anything else → None (graceful fallback rather than
        raising; same posture as the TS parser).

    Why graceful fallback rather than HTTP 400: the audit / dead-
    letter endpoints are read-only and frequently embedded in
    saved URLs, dashboard widgets, etc. A stale URL with
    `since_days=abc` rendering "all time" is operationally fine;
    an HTTP 400 would break the page.
    """
    if value is None or value == "":
        return None
    try:
        n = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if n < 1 or n > MAX_SINCE_DAYS:
        return None
    return n


def format_relative_age_vn(then: datetime | None, now: datetime) -> str:
    """Format a past datetime as "23 phút trước" / "3 ngày trước".

    Vietnamese-first per project convention. Mirrors the TS
    `formatRelativeAge` thresholds.

      * < 60s  → "vừa xong"
      * < 60m  → "<N> phút trước"
      * < 24h  → "<N> giờ trước"
      * < 30d  → "<N> ngày trước"
      * < 12mo → "<N> tháng trước"
      * else   → "<N> năm trước"

    Future / None / malformed → handled defensively:
      * None → "" (no-op for chained renderers)
      * future-dated → "trong tương lai" (clock skew defense)
    """
    if then is None:
        return ""
    delta = now - then
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return "trong tương lai"
    if seconds < 60:
        return "vừa xong"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} phút trước"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} giờ trước"
    days = hours // 24
    if days < 30:
        return f"{days} ngày trước"
    months = days // 30
    if months < 12:
        return f"{months} tháng trước"
    years = days // 365
    return f"{years} năm trước"
