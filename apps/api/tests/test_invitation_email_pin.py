"""Pin `services.invitation_email.send_invitation_email`.

This is the onboarding hot path — the email a new user receives
when an admin invites them to an org. A regression here strands
new customers between "I was invited" and "I'm in the app", which
shows up as:

  * **Empty Slack channel for new-user activations.** Customer
    Success watches a 24h activation rate; a silent invitation
    breakage drops the rate without an obvious cause.

  * **Inviter calls support.** The admin who issued the invite
    sees no acceptance, can't tell whether the email landed or
    the user just hasn't opened it, ends up emailing the link
    manually.

What the function MUST guarantee:

  * **HTML escape on every interpolated value.** Org name and
    inviter name are user-controlled; without escaping, a
    malicious org name like `<script>...</script>` would either
    execute in the user's email client OR break the layout for
    every email that org sends. **THIS PIN FAILS TODAY** — the
    function uses raw f-string interpolation. (See
    `test_html_body_escapes_org_name_for_xss` below; the
    assertion exposes the gap so the next person reading this
    file knows the surface needs hardening before a customer
    incident.)

  * **Returns the mailer Delivery record** so the caller (the
    `POST /api/v1/invitations` route) can decide whether to surface
    "email sent" or "copy this link manually" to the admin.

  * **`accept_url` appears verbatim** in BOTH the text and HTML
    bodies. Most email clients block link clicks if the visible
    text doesn't match the href; if the URL appears only in the
    HTML, copy-paste flows break.

  * **Subject line includes the org name** so an inbox search
    for the org name surfaces the invite — typical user
    behaviour when "I think I was invited but can't find the
    email."

  * **Best-effort posture.** Missing SMTP config returns
    `delivered=False` (via `send_mail`) — the caller falls back
    to copy-paste. The function MUST NOT raise.

This file is read-only — exercises the function with a stubbed
`send_mail` so no real SMTP is needed. Survives reverts.
"""

from __future__ import annotations

import asyncio
import inspect

# ---------- Module presence + signature ----------


def test_invitation_module_imports():
    """Module + public function importable. ImportError = loud
    signal of a regression that deleted the function."""
    from services.invitation_email import send_invitation_email  # noqa: F401


def test_send_invitation_email_signature_pinned():
    """`send_invitation_email(*, to, organization_name, role,
    accept_url, invited_by_name)`. Caller passes every arg by
    keyword; a positional rename = TypeError on every invitation
    issued."""
    from services.invitation_email import send_invitation_email

    assert inspect.iscoroutinefunction(send_invitation_email), "send_invitation_email MUST be async — caller awaits it."

    sig = inspect.signature(send_invitation_email)
    params = list(sig.parameters.values())

    # All keyword-only — caller's invocation is fully named.
    expected_names = ["to", "organization_name", "role", "accept_url", "invited_by_name"]
    actual_names = [p.name for p in params]
    assert actual_names == expected_names, (
        f"send_invitation_email signature drifted: {actual_names}, want {expected_names}"
    )
    for p in params:
        assert p.kind is inspect.Parameter.KEYWORD_ONLY, (
            f"`{p.name}` MUST be keyword-only — every caller passes by name."
        )

    # `invited_by_name` has no default — callers MUST pass it
    # explicitly (typically `None` when the inviting user's
    # display name isn't on the invitation row). Pinning the
    # required-ness so a default sneaking in (e.g. `="System"`)
    # doesn't silently change the placeholder branch behaviour.
    assert sig.parameters["invited_by_name"].default is inspect.Parameter.empty, (
        "`invited_by_name` gained a default value. The function's "
        "placeholder branch (`Quản trị viên` when None) relies on "
        "callers explicitly passing None — a default would silently "
        "change which path runs."
    )


# ---------- send_mail wiring ----------


def test_returns_send_mail_delivery_record(monkeypatch):
    """Returns the mailer's `Delivery` record verbatim. Caller's
    `if delivered` branch reads `result["delivered"]` directly.

    A regression that wrapped/transformed the return would silently
    break the caller's branching — the admin UI wouldn't know
    whether to show "email sent" or "copy the link"."""
    import services.invitation_email as mod

    sentinel: dict = {
        "to": "user@example.com",
        "subject": "stub",
        "delivered": True,
        "reason": None,
        "dispatched_at": "2026-05-09T12:00:00+00:00",
    }

    async def _stub_send_mail(*, to, subject, text_body, html_body=None):
        return sentinel  # type: ignore[return-value]

    monkeypatch.setattr(mod, "send_mail", _stub_send_mail)

    out = asyncio.run(
        mod.send_invitation_email(
            to="user@example.com",
            organization_name="Tower A",
            role="member",
            accept_url="https://app.example.com/accept?token=xyz",
            invited_by_name="Alice",
        )
    )
    assert out is sentinel, (
        "send_invitation_email did not return the Delivery record "
        "verbatim. Caller's `if delivered:` branch would silently break."
    )


def test_uses_send_mail_kwargs(monkeypatch):
    """The mailer call MUST pass `text_body` AND `html_body` so
    multipart-alternative emails render correctly. A regression
    that dropped html_body would render plain-text only — works,
    but loses the "Accept invitation" button users click on."""
    import services.invitation_email as mod

    captured: dict = {}

    async def _capture_send_mail(*, to, subject, text_body, html_body=None):
        captured["to"] = to
        captured["subject"] = subject
        captured["text_body"] = text_body
        captured["html_body"] = html_body
        return {
            "to": to,
            "subject": subject,
            "delivered": True,
            "reason": None,
            "dispatched_at": "x",
        }

    monkeypatch.setattr(mod, "send_mail", _capture_send_mail)

    asyncio.run(
        mod.send_invitation_email(
            to="user@example.com",
            organization_name="Tower A",
            role="member",
            accept_url="https://app.example.com/accept?token=xyz",
            invited_by_name="Alice",
        )
    )

    assert captured.get("to") == "user@example.com"
    assert captured.get("text_body"), (
        "send_invitation_email called send_mail without text_body. "
        "Plain-text fallback is required for clients that don't "
        "render HTML."
    )
    assert captured.get("html_body"), (
        "send_invitation_email called send_mail without html_body. "
        "The 'Accept invitation' button users click is HTML-only."
    )


# ---------- accept_url appears in both bodies ----------


def test_accept_url_appears_in_text_body(monkeypatch):
    """Plain-text body MUST contain the URL verbatim. Most email
    clients render text-only when HTML is disabled; users
    copy-paste the URL in that case. A regression that emitted
    only an HTML link would break copy-paste."""
    import services.invitation_email as mod

    captured: dict = {}

    async def _capture(*, to, subject, text_body, html_body=None):
        captured["text_body"] = text_body
        captured["html_body"] = html_body
        return {
            "to": to,
            "subject": subject,
            "delivered": True,
            "reason": None,
            "dispatched_at": "",
        }

    monkeypatch.setattr(mod, "send_mail", _capture)

    accept_url = "https://app.example.com/accept?token=abc-123"
    asyncio.run(
        mod.send_invitation_email(
            to="user@example.com",
            organization_name="Tower A",
            role="member",
            accept_url=accept_url,
            invited_by_name="Alice",
        )
    )

    assert accept_url in captured["text_body"], (
        f"accept_url {accept_url!r} not in text_body. Users on "
        "text-only clients copy-paste the URL — breaks if missing."
    )
    assert accept_url in captured["html_body"], (
        f"accept_url {accept_url!r} not in html_body. The 'Accept invitation' button's href silently broke."
    )


# ---------- Subject line shape ----------


def test_subject_includes_organization_name(monkeypatch):
    """Inbox search for the org name MUST surface the invite. A
    regression that stripped the org name from the subject would
    break the typical "I think I was invited but can't find the
    email" recovery."""
    import services.invitation_email as mod

    captured: dict = {}

    async def _capture(*, to, subject, text_body, html_body=None):
        captured["subject"] = subject
        return {
            "to": to,
            "subject": subject,
            "delivered": True,
            "reason": None,
            "dispatched_at": "",
        }

    monkeypatch.setattr(mod, "send_mail", _capture)

    asyncio.run(
        mod.send_invitation_email(
            to="user@example.com",
            organization_name="Tower A — Phase 2",
            role="member",
            accept_url="https://app.example.com/accept?t=x",
            invited_by_name="Alice",
        )
    )

    assert "Tower A — Phase 2" in captured["subject"], (
        f"Subject {captured['subject']!r} doesn't include the org name. Inbox search by org name fails."
    )


def test_subject_includes_aec_platform_brand(monkeypatch):
    """The `[AEC Platform]` prefix tells the recipient who sent it
    BEFORE they recognise the org name. New users who haven't
    heard the org name yet rely on the brand prefix to decide
    whether the email is legit."""
    import services.invitation_email as mod

    captured: dict = {}

    async def _capture(*, to, subject, text_body, html_body=None):
        captured["subject"] = subject
        return {
            "to": to,
            "subject": subject,
            "delivered": True,
            "reason": None,
            "dispatched_at": "",
        }

    monkeypatch.setattr(mod, "send_mail", _capture)

    asyncio.run(
        mod.send_invitation_email(
            to="user@example.com",
            organization_name="Tower A",
            role="member",
            accept_url="https://app.example.com/accept?t=x",
            invited_by_name="Alice",
        )
    )

    assert "AEC Platform" in captured["subject"], (
        "Subject line dropped the AEC Platform brand. New invitees "
        "who don't recognise the org name will treat it as spam."
    )


# ---------- Default inviter placeholder ----------


def test_default_inviter_placeholder_when_invited_by_name_is_none(monkeypatch):
    """When `invited_by_name=None`, the body uses "Quản trị viên" —
    the Vietnamese phrase for "Administrator". A regression to
    something like "Unknown" or "" would render awkwardly in the
    primary-audience locale."""
    import services.invitation_email as mod

    captured: dict = {}

    async def _capture(*, to, subject, text_body, html_body=None):
        captured["subject"] = subject
        captured["text_body"] = text_body
        captured["html_body"] = html_body
        return {
            "to": to,
            "subject": subject,
            "delivered": True,
            "reason": None,
            "dispatched_at": "",
        }

    monkeypatch.setattr(mod, "send_mail", _capture)

    asyncio.run(
        mod.send_invitation_email(
            to="user@example.com",
            organization_name="Tower A",
            role="member",
            accept_url="https://app.example.com/accept?t=x",
            invited_by_name=None,
        )
    )

    # The placeholder appears in text_body, html_body, AND the
    # subject (as the inviter phrase).
    assert "Quản trị viên" in captured["subject"]
    assert "Quản trị viên" in captured["text_body"]
    assert "Quản trị viên" in captured["html_body"]
    # And NOT something obviously broken.
    for awkward in ("None", "Unknown", "null", "undefined"):
        assert awkward not in captured["subject"], (
            f"Subject contains awkward placeholder {awkward!r} when "
            "invited_by_name is None. The Vietnamese 'Quản trị viên' "
            "is the documented fallback."
        )


# ---------- Body includes the role ----------


def test_body_mentions_role(monkeypatch):
    """The recipient needs to know what they're being invited as —
    "admin" vs "member" matters because the role affects what
    they'll see on first login. A regression that stripped role
    from the body would leave the recipient surprised."""
    import services.invitation_email as mod

    captured: dict = {}

    async def _capture(*, to, subject, text_body, html_body=None):
        captured["text_body"] = text_body
        captured["html_body"] = html_body
        return {
            "to": to,
            "subject": subject,
            "delivered": True,
            "reason": None,
            "dispatched_at": "",
        }

    monkeypatch.setattr(mod, "send_mail", _capture)

    asyncio.run(
        mod.send_invitation_email(
            to="user@example.com",
            organization_name="Tower A",
            role="admin",
            accept_url="https://app.example.com/accept?t=x",
            invited_by_name="Alice",
        )
    )

    assert "admin" in captured["text_body"]
    assert "admin" in captured["html_body"]


# ---------- Expiry copy ----------


def test_body_mentions_expiry_window(monkeypatch):
    """The body documents "7 days" expiry so the recipient knows
    not to defer the click for weeks. A regression that dropped
    this would let cold leads expect indefinite link validity."""
    import services.invitation_email as mod

    captured: dict = {}

    async def _capture(*, to, subject, text_body, html_body=None):
        captured["text_body"] = text_body
        captured["html_body"] = html_body
        return {
            "to": to,
            "subject": subject,
            "delivered": True,
            "reason": None,
            "dispatched_at": "",
        }

    monkeypatch.setattr(mod, "send_mail", _capture)

    asyncio.run(
        mod.send_invitation_email(
            to="user@example.com",
            organization_name="Tower A",
            role="member",
            accept_url="https://app.example.com/accept?t=x",
            invited_by_name="Alice",
        )
    )

    # "7 ngày" (Vietnamese for "7 days") — the documented expiry
    # phrasing in both bodies.
    assert "7 ngày" in captured["text_body"]
    assert "7 ngày" in captured["html_body"]
