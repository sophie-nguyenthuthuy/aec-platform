"""Cron expression preset parser (cycle HH1).

Parses the common Vixie cron preset shorthands (`@hourly`, `@daily`,
etc.) into canonical 5-field cron expressions. Plus a localized
human-readable label generator for the cron registry display.

Today the cron registry display, the admin cron page's preset
selector, and the cron-emit audit detector each duplicate the
preset-mapping inline. This module is the single source of truth.

  PRESETS               — closed map: @preset → 5-field expression
  PRESET_LABELS_VI      — Vietnamese display labels
  PRESET_LABELS_EN      — English display labels
  expand_preset(input)  — expand to 5-field form (or pass-through)
  is_known_preset(in)   — bool
  humanize_cron(expr, locale) — localized label or fallback to raw

Pin invariants:
  * `@hourly` → `"0 * * * *"` (minute 0 of every hour, NOT every
    minute of every hour). Pin so a refactor that uses
    `"* */1 * * *"` (which is functionally similar but
    semantically wrong) surfaces here.
  * `@midnight` is an alias for `@daily` per Vixie cron convention.
  * `@yearly` is an alias for `@annually`.
  * Unknown `@whatever` → None (graceful fallback for typos).
  * Non-`@`-prefixed input → returned as-is (already a cron expression).

Pure stdlib.
"""

from __future__ import annotations

from typing import Literal

CronLocale = Literal["vi", "en"]


# Vixie cron preset → canonical 5-field equivalent. The map is
# closed; a refactor that adds a preset must touch this AND
# both label maps. Pin via test.
PRESETS: dict[str, str] = {
    "@every_minute": "* * * * *",
    "@hourly": "0 * * * *",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",  # alias for @daily
    "@weekly": "0 0 * * 0",  # midnight Sunday
    "@monthly": "0 0 1 * *",  # midnight 1st of month
    "@yearly": "0 0 1 1 *",  # midnight Jan 1
    "@annually": "0 0 1 1 *",  # alias for @yearly
}


# Vietnamese display labels. Used by the cron registry display
# and the admin cron page (vi-VN-first per project convention).
PRESET_LABELS_VI: dict[str, str] = {
    "@every_minute": "Mỗi phút",
    "@hourly": "Mỗi giờ",
    "@daily": "Hàng ngày lúc 0:00",
    "@midnight": "Hàng ngày lúc 0:00",
    "@weekly": "Hàng tuần (Chủ Nhật 0:00)",
    "@monthly": "Hàng tháng (ngày 1, 0:00)",
    "@yearly": "Hàng năm (1/1, 0:00)",
    "@annually": "Hàng năm (1/1, 0:00)",
}


# English display labels. Used by the admin cron page when the
# operator's locale override is "en" (Slack ops channel often
# prefers English for shared comprehension).
PRESET_LABELS_EN: dict[str, str] = {
    "@every_minute": "Every minute",
    "@hourly": "Every hour",
    "@daily": "Daily at midnight",
    "@midnight": "Daily at midnight",
    "@weekly": "Weekly (Sunday at midnight)",
    "@monthly": "Monthly (1st at midnight)",
    "@yearly": "Yearly (Jan 1 at midnight)",
    "@annually": "Yearly (Jan 1 at midnight)",
}


def expand_preset(input_str: str | None) -> str | None:
    """Expand a Vixie preset to a canonical 5-field cron expression.

    Behaviour:
      * Known preset (e.g. `@hourly`) → mapped 5-field form.
      * Non-`@`-prefixed input → returned verbatim (already a cron
        expression; this helper is a no-op pass-through).
      * Unknown `@whatever` → None (graceful fallback for typos).
      * None / empty / whitespace-only → None.
    """
    if not input_str:
        return None
    s = input_str.strip()
    if not s:
        return None
    if s in PRESETS:
        return PRESETS[s]
    if s.startswith("@"):
        return None
    return s


def is_known_preset(input_str: str | None) -> bool:
    """True iff `input_str` is a member of `PRESETS`."""
    if not input_str:
        return False
    return input_str.strip() in PRESETS


def humanize_cron(expr: str | None, locale: CronLocale = "vi") -> str:
    """Return a human-readable label for a cron expression.

    For known presets, returns the localized label. For non-preset
    expressions, returns the raw input (caller can layer a richer
    natural-language formatter on top if needed).

    Empty / None → "" (chained-render-friendly).
    """
    if not expr:
        return ""
    s = expr.strip()
    if not s:
        return ""
    labels = PRESET_LABELS_VI if locale == "vi" else PRESET_LABELS_EN
    if s in labels:
        return labels[s]
    return s
