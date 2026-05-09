"""Thin Slack webhook delivery — used by `services.ops_alerts`.

Mirrors the shape of `services.mailer.send_mail`: a single async
function that returns `{delivered, reason}` so callers can route
without try/except spaghetti. Designed to be replaceable — the only
public contract is `send_slack(text, blocks=None) -> dict`.

Why a separate module rather than inlining into `ops_alerts`:
  * Future callers (RFQ-deadline summary, weekly digest) want the
    same delivery primitive. Having one canonical helper means each
    new caller is a one-import dependency.
  * Easier to swap for `slack_sdk.WebhookClient` if we outgrow the
    raw-webhook approach (Slack apps with multiple channels, OAuth
    scopes, etc.).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from core.config import get_settings

logger = logging.getLogger(__name__)


# How long we wait for Slack to acknowledge a webhook POST. Slack's
# infrastructure is fast (~50ms typical) but a sluggish hook can hang
# the originating cron. 5s is generous — anything slower is a Slack
# outage and should fail-open rather than starve the queue.
_SLACK_TIMEOUT_SECONDS = 5.0


async def send_slack(*, text: str, blocks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """POST a message to the configured Slack webhook.

    Returns `{delivered: bool, reason: str | None, status: int | None}`
    so callers can log + count the same way they do for `send_mail`.

    Returns `delivered=False, reason="slack_not_configured"` when the
    webhook URL is empty — same shape as the no-SMTP-configured path
    in the mailer. Lets `ops_alerts` count "skipped" without try/except.

    The `text` is a fallback shown in notifications + IDE hovers. If
    `blocks` is provided, those drive the in-app rendering — see
    https://api.slack.com/reference/block-kit. We don't validate the
    block schema here; Slack returns 400 on invalid blocks and we
    surface the body as the reason.
    """
    url = get_settings().ops_slack_webhook_url
    if not url:
        return {"delivered": False, "reason": "slack_not_configured", "status": None}

    payload: dict[str, Any] = {"text": text}
    if blocks:
        payload["blocks"] = blocks

    try:
        async with httpx.AsyncClient(timeout=_SLACK_TIMEOUT_SECONDS) as client:
            resp = await client.post(url, json=payload)
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        logger.warning("slack.send_slack: transport failure: %s", exc)
        return {"delivered": False, "reason": f"transport:{type(exc).__name__}", "status": None}
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("slack.send_slack: unexpected error: %s", exc)
        return {"delivered": False, "reason": f"error:{type(exc).__name__}", "status": None}

    if resp.status_code != 200:
        # Slack returns the failure reason as plain text in the body.
        # Truncate to keep log volume sane (some 400s spit a screenful
        # of escape sequences).
        body_preview = (resp.text or "")[:200]
        logger.warning(
            "slack.send_slack: %d %s — %s",
            resp.status_code,
            resp.reason_phrase or "",
            body_preview,
        )
        return {
            "delivered": False,
            "reason": f"slack_http_{resp.status_code}",
            "status": resp.status_code,
        }

    return {"delivered": True, "reason": None, "status": 200}


def render_slack_drift_alert(*, slug: str, summary: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    """Build the (fallback_text, blocks) pair for a drift Slack message.

    Matches the structure `_render_drift_alert` produces for email,
    but uses Slack Block Kit so the rendering looks native. Falls
    back gracefully on Slack receivers that don't support blocks
    (the `text` is the universal display).
    """
    scraped = summary.get("scraped", 0)
    unmatched = summary.get("unmatched", 0)
    ratio = (unmatched / scraped) if scraped else 0.0
    sample = summary.get("unmatched_sample") or []

    text = f":warning: scraper.drift[{slug}]: {ratio * 100:.0f}% unmatched"

    sample_lines = "\n".join(f"• `{name}`" for name in sample[:5])
    if len(sample) > 5:
        sample_lines += f"\n• …and {len(sample) - 5} more"
    if not sample_lines:
        sample_lines = "_(no sample — likely a config bug)_"

    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"Drift on scraper: {slug}"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Scraped:*\n{scraped}"},
                {"type": "mrkdwn", "text": f"*Matched:*\n{summary.get('matched', 0)}"},
                {
                    "type": "mrkdwn",
                    "text": f"*Unmatched:*\n{unmatched} ({ratio * 100:.0f}%)",
                },
                {"type": "mrkdwn", "text": f"*Written:*\n{summary.get('written', 0)}"},
            ],
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Top unmatched names:*\n{sample_lines}",
            },
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        f"`GET /api/v1/admin/scraper-runs?slug={slug}` · <docs/scraper-drift-monitoring.md|runbook>"
                    ),
                }
            ],
        },
    ]
    return text, blocks
