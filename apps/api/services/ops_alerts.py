"""Platform-ops notifications.

Distinct from `services.notifications` — that module is the per-user
activity-digest pipeline (tenant-scoped, daily). This one fires
**ad-hoc, cross-tenant alerts** when something the platform owners
need to know about happens:

  * Scraper drift > threshold (the inaugural caller).
  * (Future) Weekly cron crash, Redis backlog spike, S3 upload
    failures from the dispatcher, etc.

Recipient resolution (in priority order):

  1. **Per-user opt-in** via `notification_preferences.key="scraper_drift"`
     with `email_enabled=true`. Joined to `users.email` cross-tenant
     (drift IS global ops data; users opt in once per org and we
     dedupe by email so a user with the pref in 3 orgs gets 1 email).
  2. **Fallback to `OPS_ALERT_EMAILS` env var** when nobody has opted
     in. Keeps existing prod deploys working — the table-driven
     opt-in is purely additive.

Best-effort: each delivery is wrapped so a single SMTP failure
doesn't propagate or block the originating job. The dispatcher logs
failures at WARNING for the slow-query / Sentry stream to pick up.
"""

from __future__ import annotations

import logging

from core.config import get_settings
from services.mailer import send_mail

logger = logging.getLogger(__name__)


# Cap on sample names included in the email body. The full list is on
# the admin endpoint (`GET /api/v1/admin/scraper-runs?slug=...`) — the
# email is meant to be a "go look" prompt, not the forensic record.
_MAX_SAMPLES_IN_EMAIL = 10

# Pref key the drift alert reads. Mirrors the value in
# `routers/notifications.py::_KNOWN_PREF_KEYS` and the user-facing
# copy in the dashboard's settings page. Constant rather than ad-hoc
# string so a future rename has one editing site.
_DRIFT_PREF_KEY = "scraper_drift"


async def _resolve_drift_recipients() -> list[str]:
    """Build the dedup'd recipient list for a drift alert.

    Reads opt-ins from `notification_preferences` first; falls back to
    `OPS_ALERT_EMAILS` only when nobody has explicitly opted in. The
    fallback is what keeps a green-field deploy with zero prefs rows
    still alerting — once the first user hits the prefs UI, the env
    var is no longer consulted.

    Cross-tenant by design: this is global ops data, not a per-tenant
    notification. Uses `AdminSessionFactory` for the same reason as
    `weekly_report_cron` / `evaluate_price_alerts`. Best-effort —
    a DB outage falls through to the env list.
    """
    explicit: list[str] = []
    try:
        from sqlalchemy import select

        from db.session import AdminSessionFactory
        from models.core import NotificationPreference, User

        async with AdminSessionFactory() as session:
            rows = (
                (
                    await session.execute(
                        select(User.email)
                        .join(
                            NotificationPreference,
                            NotificationPreference.user_id == User.id,
                        )
                        .where(
                            NotificationPreference.key == _DRIFT_PREF_KEY,
                            NotificationPreference.email_enabled.is_(True),
                        )
                        .distinct()
                    )
                )
                .scalars()
                .all()
            )
            explicit = [r for r in rows if r]
    except Exception as exc:  # pragma: no cover — defensive against a temporarily-down ops DB
        logger.warning("ops_alerts.drift: pref-resolution failed: %s", exc)

    if explicit:
        return explicit

    # No opt-ins → legacy fallback. The buyer-facing UI shows "(no
    # subscribers — falls back to OPS_ALERT_EMAILS)" so this isn't
    # invisible.
    return list(get_settings().ops_alert_emails)


async def send_drift_alert(*, slug: str, summary: dict) -> int:
    """Email opted-in users (or `OPS_ALERT_EMAILS` fallback) about a drift event.

    `summary` is the same dict `services.price_scrapers.run_scraper`
    returns — needs `slug`, `scraped`, `unmatched`, `unmatched_sample`.
    Returns the count of *delivered* emails (best-effort — a recipient
    whose SMTP fails is logged + skipped).

    Returns 0 cleanly when:
      * Nobody has opted in AND `OPS_ALERT_EMAILS` is empty.
      * SMTP isn't configured (mailer skips, returns delivered=False).
      * Every send raised — exceptions swallowed per-recipient.
    """
    recipients = await _resolve_drift_recipients()

    # Slack delivery runs alongside email — they're independent
    # channels. A configured Slack webhook fires even when no users
    # have opted into email; conversely, an empty webhook URL
    # silently no-ops without affecting email counts.
    slack_delivered = await _maybe_send_slack(slug=slug, summary=summary)

    if not recipients:
        if slack_delivered:
            # Slack alone is a valid configuration — Slack is the
            # primary ops channel for some teams and email is just
            # the redundancy.
            return 0
        logger.info("ops_alerts.drift skipped — no opted-in users, no OPS_ALERT_EMAILS, no Slack")
        return 0

    subject, text_body = _render_drift_alert(slug=slug, summary=summary)

    delivered = 0
    for addr in recipients:
        try:
            result = await send_mail(to=addr, subject=subject, text_body=text_body)
            if result.get("delivered"):
                delivered += 1
            else:
                # Mailer returns `delivered=False` for the
                # smtp-unconfigured / bounce / etc. paths; surface in
                # logs so an ops dashboard query can correlate.
                logger.warning(
                    "ops_alerts.drift: delivery to %s skipped (%s)",
                    addr,
                    result.get("reason"),
                )
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("ops_alerts.drift: send to %s raised: %s", addr, exc)
    return delivered


async def _maybe_send_slack(*, slug: str, summary: dict) -> bool:
    """Best-effort Slack delivery. Returns True iff a message landed.

    Lazy-imports `services.slack` so this module's existing tests don't
    pull httpx into their import graph. Failures are logged + swallowed —
    Slack being down can't block email delivery.
    """
    try:
        from services.slack import render_slack_drift_alert, send_slack
    except ImportError:  # pragma: no cover — dep should always be there
        return False

    text, blocks = render_slack_drift_alert(slug=slug, summary=summary)
    try:
        result = await send_slack(text=text, blocks=blocks)
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("ops_alerts.drift: slack send raised: %s", exc)
        return False

    if result.get("delivered"):
        return True
    reason = result.get("reason")
    # `slack_not_configured` is the silent no-op — anything else is
    # a real failure worth surfacing.
    if reason and reason != "slack_not_configured":
        logger.warning("ops_alerts.drift: slack delivery skipped (%s)", reason)
    return False


def _render_drift_alert(*, slug: str, summary: dict) -> tuple[str, str]:
    """Build the (subject, body) pair for the alert email.

    Body is plain text — most ops inboxes (PagerDuty / OpsGenie email
    triggers) prefer text, and we don't need any styling for a
    short-form alert.
    """
    scraped = summary.get("scraped", 0)
    unmatched = summary.get("unmatched", 0)
    ratio = (unmatched / scraped) if scraped else 0.0
    sample = summary.get("unmatched_sample") or []

    subject = f"[AEC ops] scraper.drift[{slug}]: {ratio * 100:.0f}% unmatched"
    sample_lines = "\n".join(f"  • {name}" for name in sample[:_MAX_SAMPLES_IN_EMAIL])
    if len(sample) > _MAX_SAMPLES_IN_EMAIL:
        sample_lines += f"\n  • …and {len(sample) - _MAX_SAMPLES_IN_EMAIL} more"

    body = (
        f"Drift threshold breached on scraper `{slug}`.\n\n"
        f"Run summary:\n"
        f"  scraped:    {scraped}\n"
        f"  matched:    {summary.get('matched', 0)}\n"
        f"  unmatched:  {unmatched} ({ratio * 100:.0f}%)\n"
        f"  written:    {summary.get('written', 0)}\n\n"
        f"Top unmatched names (write a regex rule for these in "
        f"`services.price_scrapers.normalizer._RULES`):\n"
        f"{sample_lines or '  (none — high ratio with no sample is a config bug)'}\n\n"
        f"Full history: GET /api/v1/admin/scraper-runs?slug={slug}\n"
        f"Runbook: docs/scraper-drift-monitoring.md\n"
    )
    return subject, body
