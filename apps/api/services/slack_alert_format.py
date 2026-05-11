"""Canonical Slack alert message formatter (cycle Y1).

Today the alert-message format rules are duplicated across:

  * `services/cron_alerts.py::_format_alert`         (cron_failure)
  * `services/cron_alerts.py::_format_stuck_alert`   (cron_stuck)
  * `services/webhook_health_alerts.py::format_alert_message`
                                                     (webhook_unhealthy)

A copy-tweak (e.g. swapping the rotating-light emoji for an
accessibility-friendly variant, changing the repeat-label phrasing,
adjusting the 500-char cap) currently means three edits in three
places — and the integrator-surface snapshot doesn't pin them
together.

This module's `format_alert(...)` is the single source of truth.
The existing formatters are expected to delegate here in a
follow-up; this cycle only ships the helper + tests so the
contract is locked down before the refactor.

Output shape:

    :rotating_light: <subject_label>: `<subject>` — <detail>
    :hourglass_flowing_sand: cron stuck: `<name>` running 142s — ...
    :rotating_light: webhook unhealthy: `<sub_id>` — 67% rate over 7d ...

Repeat label: when `alert_count >= 2`, the helper appends
" (still <state>, <count>×)" right after the backtick-quoted
subject — matches the cron / webhook formatters' "still failing"
/ "still stuck" / "still unhealthy" wording.

Cap: 500 chars total. Truncation appends "…" so the partial
message is visibly trimmed.

Pure Python, no I/O, no Slack SDK. The caller passes the result
to `services.slack.send_slack`.
"""

from __future__ import annotations

from dataclasses import dataclass

# Slack message body cap. The actual Slack limit is 40000 chars; we
# cap aggressively for readability — operators reading on a phone
# preview see ~144 chars, so anything longer is wasted lines.
# Pin so a refactor that bumps to 1000 surfaces here, not as a
# Slack message that fills three notification cards.
MAX_BODY_CHARS = 500


# Standard icons per alert kind. Each is a Slack emoji slug
# (Slack renders `:rotating_light:` as 🚨). Pulling them out makes
# accessibility refactors a one-line change.
ICON_FAILURE = ":rotating_light:"
ICON_STUCK = ":hourglass_flowing_sand:"
ICON_HEALTH = ":rotating_light:"  # webhook health uses the same
# alarm icon as cron failure


@dataclass(frozen=True)
class AlertSpec:
    """Inputs for `format_alert`. Frozen so the caller-side contract
    is explicit at the type level and a future refactor that
    changes the kwargs can't silently re-order them."""

    icon: str
    subject_label: str  # e.g. "cron failed", "cron stuck", "webhook unhealthy"
    subject: str  # e.g. "cron:weekly_report" or "abc-123"
    detail: str  # e.g. "RuntimeError: db down" or "67% rate over 7d (200 attempts)"
    repeat_state: str  # e.g. "failing", "stuck", "unhealthy" — only used
    # when alert_count >= 2 ("still <state>, N×")
    alert_count: int = 1


def format_alert(spec: AlertSpec) -> str:
    """Compose the canonical Slack body for an alert.

    Format:

        <icon> <subject_label>: `<subject>`<repeat?> — <detail>

    Where `<repeat>` is " (still <repeat_state>, <count>×)" when
    `alert_count >= 2`, else empty.

    Truncation: capped at MAX_BODY_CHARS with "…" suffix on the
    truncated tail. The truncation lands at MAX_BODY_CHARS - 1 so
    the suffix fits inside the cap.
    """
    repeat_label = ""
    if spec.alert_count >= 2:
        repeat_label = f" (still {spec.repeat_state}, {spec.alert_count}×)"
    msg = f"{spec.icon} {spec.subject_label}: `{spec.subject}`{repeat_label} — {spec.detail}"
    if len(msg) > MAX_BODY_CHARS:
        return msg[: MAX_BODY_CHARS - 1] + "…"
    return msg


# ---------- Convenience wrappers per alert kind ----------
#
# These wrappers exist so the call site reads naturally without
# having to remember the icon / repeat_state vocabulary for each
# alert type. They all delegate to `format_alert`.


def format_cron_failure(
    *,
    cron_name: str,
    error_message: str,
    duration_ms: int | None = None,
    alert_count: int = 1,
) -> str:
    """Slack body for a fresh cron failure (R3 path)."""
    duration_str = f" ({duration_ms}ms)" if duration_ms is not None else ""
    return format_alert(
        AlertSpec(
            icon=ICON_FAILURE,
            subject_label="cron failed",
            subject=cron_name,
            detail=f"{error_message}{duration_str}".strip() or "(no error message)",
            repeat_state="failing",
            alert_count=alert_count,
        )
    )


def format_cron_stuck(
    *,
    cron_name: str,
    elapsed_ms: int,
    p95_ms: int,
    alert_count: int = 1,
) -> str:
    """Slack body for a stuck cron (N2 path)."""
    elapsed_s = elapsed_ms / 1000.0
    multiple = elapsed_ms / p95_ms if p95_ms else 0
    detail = (
        f"running {elapsed_s:.0f}s (~{multiple:.1f}× p95). Worker may "
        f"have crashed mid-run; check `/admin/crons/{cron_name}` for the row id."
    )
    return format_alert(
        AlertSpec(
            icon=ICON_STUCK,
            subject_label="cron stuck",
            subject=cron_name,
            detail=detail,
            repeat_state="stuck",
            alert_count=alert_count,
        )
    )


def format_webhook_unhealthy(
    *,
    subscription_id: str,
    subscription_url: str,
    rate: float,
    total_attempts: int,
    failed_count: int,
    alert_count: int = 1,
) -> str:
    """Slack body for an unhealthy webhook subscription (W1 path)."""
    rate_pct = int(round(rate * 100))
    detail = (
        f"{rate_pct}% delivery rate over 7d "
        f"({total_attempts} attempts, {failed_count} failed). "
        f"Receiver: {subscription_url}"
    )
    return format_alert(
        AlertSpec(
            icon=ICON_HEALTH,
            subject_label="webhook unhealthy",
            subject=subscription_id,
            detail=detail,
            repeat_state="unhealthy",
            alert_count=alert_count,
        )
    )
