"""Unit tests for `services/invitation_email.py`.

The service is a thin wrapper around `services.mailer.send_mail` —
its job is to build the right subject + body shape (Vietnamese-first
templates, accept-link prominent, fallback "Quản trị viên" when the
inviter name is null). Mock `send_mail` and assert what got passed in.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_send_invitation_email_passes_typed_subject_and_link(monkeypatch):
    captured = {}

    async def fake_send_mail(*, to, subject, text_body, html_body=None):
        captured["to"] = to
        captured["subject"] = subject
        captured["text_body"] = text_body
        captured["html_body"] = html_body
        return "delivery-1"

    monkeypatch.setattr("services.invitation_email.send_mail", fake_send_mail)

    from services.invitation_email import send_invitation_email

    result = await send_invitation_email(
        to="newuser@example.com",
        organization_name="Acme Construction",
        role="member",
        accept_url="https://app.aec.test/invite/abc123",
        invited_by_name="Thuy",
    )

    # Mailer return value bubbles up unchanged.
    assert result == "delivery-1"

    assert captured["to"] == "newuser@example.com"
    # Subject embeds inviter + org name + the bracketed app prefix.
    assert "Acme Construction" in captured["subject"]
    assert "Thuy" in captured["subject"]
    assert captured["subject"].startswith("[AEC Platform]")

    # Both bodies present (text + HTML — a multipart-friendly mailer
    # uses the right one per recipient client).
    assert captured["text_body"] is not None
    assert captured["html_body"] is not None

    # Accept-link must appear in BOTH bodies — the text body is the
    # fallback for clients that strip HTML.
    assert "https://app.aec.test/invite/abc123" in captured["text_body"]
    assert "https://app.aec.test/invite/abc123" in captured["html_body"]

    # Role + org name visible in body so the recipient can decide
    # whether to accept without clicking through.
    assert "member" in captured["text_body"]
    assert "Acme Construction" in captured["text_body"]


async def test_send_invitation_email_falls_back_to_quan_tri_vien_when_inviter_unknown(
    monkeypatch,
):
    """`invited_by_name=None` happens when the inviter row was deleted
    but the invitation row still references it. Email must still go
    out; subject just uses the generic 'Quản trị viên' label."""
    captured = {}

    async def fake_send_mail(**kwargs):
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr("services.invitation_email.send_mail", fake_send_mail)

    from services.invitation_email import send_invitation_email

    await send_invitation_email(
        to="x@y.com",
        organization_name="Org",
        role="admin",
        accept_url="https://app/x",
        invited_by_name=None,
    )

    assert "Quản trị viên" in captured["subject"]
    assert "Quản trị viên" in captured["text_body"]


async def test_send_invitation_email_html_includes_button_styling(monkeypatch):
    """HTML body must render a real button-styled anchor (not just a bare
    URL) — that's the visible call-to-action for invitees on email
    clients that render HTML. Pin a couple of structural markers so a
    refactor doesn't silently strip the styling."""
    captured = {}

    async def fake_send_mail(**kwargs):
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr("services.invitation_email.send_mail", fake_send_mail)

    from services.invitation_email import send_invitation_email

    await send_invitation_email(
        to="x@y.com",
        organization_name="Org",
        role="member",
        accept_url="https://app/x",
        invited_by_name="Admin",
    )

    html = captured["html_body"]
    # Inline-styled anchor with the accept-link as href.
    assert 'href="https://app/x"' in html
    assert "Chấp nhận lời mời" in html
    # The "or paste this URL" fallback section that handles email
    # clients that strip <a> styling — without this, recipients on
    # plaintext-mode see only "Click here" with nothing clickable.
    assert "Hoặc dán liên kết" in html
