"""Minimal stdlib-based async mailer wrapper.

Uses `smtplib` inside `asyncio.to_thread` so it is safe to call from async code.
If SMTP isn't configured (dev/test), falls back to a logged "skipped" delivery
and still returns a delivery record so callers can record intent uniformly.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import TypedDict

from core.config import get_settings

logger = logging.getLogger(__name__)


class Delivery(TypedDict):
    to: str
    subject: str
    delivered: bool
    reason: str | None
    dispatched_at: str


async def send_mail(*, to: str, subject: str, text_body: str, html_body: str | None = None) -> Delivery:
    settings = get_settings()
    ts = datetime.now(UTC).isoformat()

    if not settings.smtp_host or not settings.smtp_user:
        logger.info("mailer.skipped smtp_unconfigured to=%s subject=%r", to, subject)
        return Delivery(
            to=to,
            subject=subject,
            delivered=False,
            reason="smtp_not_configured",
            dispatched_at=ts,
        )

    msg = EmailMessage()
    msg["From"] = settings.email_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text_body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")

    try:
        await asyncio.to_thread(_send_sync, msg, settings)
        logger.info("mailer.sent to=%s subject=%r", to, subject)
        return Delivery(to=to, subject=subject, delivered=True, reason=None, dispatched_at=ts)
    except Exception as exc:  # pragma: no cover — network path
        logger.exception("mailer.failed to=%s subject=%r", to, subject)
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
