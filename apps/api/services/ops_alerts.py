"""Platform-ops notifications.

Distinct from `services.notifications` — that module is the per-user
activity-digest pipeline (tenant-scoped, daily). This one fires
**ad-hoc, cross-tenant alerts** when something the platform owners
need to know about happens:

  * Scraper drift > threshold (the inaugural caller).
  * (Future) Weekly cron crash, Redis backlog spike, S3 upload
    failures from the dispatcher, etc.

Recipients come from the `OPS_ALERT_EMAILS` env (comma-separated),
NOT from `org_members` — drift is global ops data, not a tenant
concern. Empty list disables alerts entirely (the alert site falls
back to log-only via `_maybe_log_drift`).

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


async def send_drift_alert(*, slug: str, summary: dict) -> int:
    """Email each `OPS_ALERT_EMAILS` recipient about a drift event.

    `summary` is the same dict `services.price_scrapers.run_scraper`
    returns — needs `slug`, `scraped`, `unmatched`, `unmatched_sample`.
    Returns the count of *delivered* emails (best-effort — a recipient
    whose SMTP fails is logged + skipped).

    Returns 0 cleanly when:
      * `OPS_ALERT_EMAILS` is empty (alerts disabled).
      * SMTP isn't configured (mailer skips, returns delivered=False).
      * Every send raised — exceptions are swallowed per-recipient
        so one bad address can't deny others.
    """
    settings = get_settings()
    if not settings.ops_alert_emails:
        # Don't even render the email body — keeps the no-recipients
        # case off the hot path.
        logger.info("ops_alerts.drift skipped — no OPS_ALERT_EMAILS configured")
        return 0

    subject, text_body = _render_drift_alert(slug=slug, summary=summary)

    delivered = 0
    for addr in settings.ops_alert_emails:
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
