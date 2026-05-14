"""Transactional email sender with Resend + SMTP backends.

The mailer is the single chokepoint every notification surface goes
through: codeguard quota threshold alerts, RFQ supplier dispatch,
invitation emails, ops drift alerts, daily activity digests, weekly
client reports. Every caller invokes `send_mail(to=, subject=,
text_body=, html_body=)` and gets back the same `Delivery` shape so
the *content* layer stays backend-agnostic.

Backend selection (first-match wins):
  1. `RESEND_API_KEY` is set → POST https://api.resend.com/emails. This
     is the recommended path for production: Resend handles DKIM/SPF
     signing, bounce processing, and reputation. No MTA babysitting.
  2. `SMTP_HOST` + `SMTP_USER` are set → STARTTLS SMTP via stdlib.
     Kept as a fallback for self-hosted customers (Vietnamese SOEs
     occasionally require email to stay inside the corporate network).
  3. Neither is set → log + return `delivered=False, reason=
     "smtp_not_configured"`. Test and dev environments don't need
     to wire either; tests assert on the Delivery record's intent,
     not on actual SMTP traffic.

Failures inside a configured backend (Resend HTTP 4xx/5xx, SMTP
timeout, DNS error) are caught and reported via `delivered=False,
reason="..."` so the caller can record + decide retry policy.
Exceptions never propagate up — a transient inbox blip should not
kill a weekly-report job that already rendered a 90-second PDF.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import TypedDict

import httpx

from core.config import get_settings

logger = logging.getLogger(__name__)


# Resend's `/emails` endpoint. Documented at https://resend.com/docs/api-reference/emails/send-email
# Single global endpoint, no per-region routing.
_RESEND_ENDPOINT = "https://api.resend.com/emails"
_RESEND_TIMEOUT_S = 15.0


class Delivery(TypedDict):
    to: str
    subject: str
    delivered: bool
    reason: str | None
    dispatched_at: str


async def send_mail(
    *, to: str, subject: str, text_body: str, html_body: str | None = None
) -> Delivery:
    """Dispatch one email via the configured backend.

    Returns a `Delivery` record regardless of success/failure so callers
    can persist a uniform audit trail.
    """
    settings = get_settings()
    ts = datetime.now(UTC).isoformat()

    # ----- Backend selection -----
    if settings.resend_api_key:
        return await _send_via_resend(
            settings, to=to, subject=subject, text_body=text_body, html_body=html_body, ts=ts
        )

    if settings.smtp_host and settings.smtp_user:
        return await _send_via_smtp(
            settings, to=to, subject=subject, text_body=text_body, html_body=html_body, ts=ts
        )

    logger.info("mailer.skipped smtp_unconfigured to=%s subject=%r", to, subject)
    return Delivery(
        to=to,
        subject=subject,
        delivered=False,
        reason="smtp_not_configured",
        dispatched_at=ts,
    )


# ---------- Resend ----------


async def _send_via_resend(
    settings,
    *,
    to: str,
    subject: str,
    text_body: str,
    html_body: str | None,
    ts: str,
) -> Delivery:
    """POST one email to Resend's `/emails` endpoint.

    Returns `delivered=True` on 2xx, `delivered=False` with a structured
    `reason` on 4xx/5xx or network error. Never raises.
    """
    payload: dict[str, str | list[str]] = {
        "from": settings.resend_from or settings.email_from,
        "to": [to],
        "subject": subject,
        "text": text_body,
    }
    if html_body:
        payload["html"] = html_body
    if settings.resend_reply_to:
        payload["reply_to"] = settings.resend_reply_to

    headers = {
        "Authorization": f"Bearer {settings.resend_api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=_RESEND_TIMEOUT_S) as client:
            resp = await client.post(_RESEND_ENDPOINT, json=payload, headers=headers)
    except httpx.HTTPError as exc:
        logger.exception("mailer.resend.network_error to=%s subject=%r", to, subject)
        return Delivery(
            to=to,
            subject=subject,
            delivered=False,
            reason=f"resend_network:{type(exc).__name__}",
            dispatched_at=ts,
        )

    if 200 <= resp.status_code < 300:
        # The Resend response body has `{"id": "..."}`; log it so we can
        # cross-reference bounce webhooks against our delivery records.
        try:
            resend_id = resp.json().get("id")
        except Exception:
            resend_id = None
        logger.info(
            "mailer.resend.sent to=%s subject=%r resend_id=%s",
            to,
            subject,
            resend_id,
        )
        return Delivery(
            to=to, subject=subject, delivered=True, reason=None, dispatched_at=ts
        )

    # 4xx / 5xx — capture the response body for the audit log, but cap
    # the slug to ~200 chars so a verbose Resend error doesn't blow up
    # a JSONB column or grep-friendly log line.
    body = (resp.text or "")[:200].replace("\n", " ")
    logger.warning(
        "mailer.resend.http_error status=%d to=%s subject=%r body=%s",
        resp.status_code,
        to,
        subject,
        body,
    )
    return Delivery(
        to=to,
        subject=subject,
        delivered=False,
        reason=f"resend_http_{resp.status_code}",
        dispatched_at=ts,
    )


# ---------- SMTP fallback ----------


async def _send_via_smtp(
    settings,
    *,
    to: str,
    subject: str,
    text_body: str,
    html_body: str | None,
    ts: str,
) -> Delivery:
    msg = EmailMessage()
    msg["From"] = settings.email_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text_body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")

    try:
        await asyncio.to_thread(_send_sync, msg, settings)
        logger.info("mailer.smtp.sent to=%s subject=%r", to, subject)
        return Delivery(
            to=to, subject=subject, delivered=True, reason=None, dispatched_at=ts
        )
    except Exception as exc:
        logger.exception("mailer.smtp.failed to=%s subject=%r", to, subject)
        return Delivery(
            to=to,
            subject=subject,
            delivered=False,
            reason=f"smtp_error:{type(exc).__name__}",
            dispatched_at=ts,
        )


def _send_sync(msg: EmailMessage, settings) -> None:
    ctx = ssl.create_default_context()
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
        smtp.ehlo()
        smtp.starttls(context=ctx)
        smtp.ehlo()
        smtp.login(settings.smtp_user, settings.smtp_password or "")
        smtp.send_message(msg)
