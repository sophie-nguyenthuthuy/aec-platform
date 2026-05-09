"""Pin the `services.mailer.send_mail` partner-email contract.

`send_mail` is the single email-delivery primitive every customer-
facing notification goes through (drift alerts, weekly digest,
invitations, RFQ-deadline reminders, retention-prune notices).
Symmetric to `services.slack.send_slack` but with SMTP + SSL
plumbing inside.

Two failure modes a regression here can produce, both bad:

  * **Silent skip with `delivered=True`** — caller logs "delivered"
    when the message was never sent. Customer never receives the
    invitation. Worst-case onboarding break.

  * **Raise instead of return Delivery** — caller's try/except
    catches the raise and treats it as a generic delivery failure;
    the `Delivery` record never lands and downstream telemetry
    (`email_deliveries`-style dashboards, `record_call`-equivalent
    audit hooks) silently skip the failed attempt.

The contract every caller relies on:

  * **Always returns a `Delivery` TypedDict.** Never raises (network
    failures get swallowed and reported via `delivered=False`,
    `reason="smtp_error:..."`).

  * **Keys on the Delivery dict are exactly `{to, subject, delivered,
    reason, dispatched_at}`.** A rename = the dashboard's
    `successful` count silently mismatches.

  * **Skipped path uses reason `"smtp_not_configured"`.** Identical
    semantics to `slack_not_configured` — distinguishes "ops disabled
    email" from "we tried and failed." Dashboards check this exact
    string.

  * **`delivered=False` whenever SMTP isn't fully configured** (host
    OR user missing). Both checks matter — partial config is the
    most common dev mistake.

This file is read-only — exercises `send_mail` with monkey-patched
settings + asyncio.to_thread stubs to avoid hitting real SMTP.
Survives reverts.
"""

from __future__ import annotations

import asyncio
import inspect

# ---------- Module presence + signature ----------


def test_mailer_module_imports():
    """All public surfaces importable. Hard ImportError on revert =
    desired loud-fail."""
    from services.mailer import Delivery, send_mail  # noqa: F401


def test_send_mail_signature_pinned():
    """`send_mail(*, to, subject, text_body, html_body=None)`.

    Callers (every notification pipeline) pass these by keyword;
    a positional rename = TypeError everywhere a notification fires.
    """
    from services.mailer import send_mail

    sig = inspect.signature(send_mail)
    params = sig.parameters

    assert set(params.keys()) == {"to", "subject", "text_body", "html_body"}, (
        f"send_mail signature drifted: {set(params.keys())}"
    )
    for name in ("to", "subject", "text_body", "html_body"):
        assert params[name].kind is inspect.Parameter.KEYWORD_ONLY, (
            f"`{name}` MUST be keyword-only — every caller passes by name."
        )

    # `html_body` defaults to None (text-only emails are the common case).
    assert params["html_body"].default is None


def test_send_mail_is_async():
    """Awaited everywhere. Sync regression = silent no-op (await on
    non-coroutine returns the function ref unchanged)."""
    from services.mailer import send_mail

    assert inspect.iscoroutinefunction(send_mail), "send_mail MUST be async — caller awaits it."


# ---------- Delivery TypedDict shape ----------


def test_delivery_typeddict_keys():
    """Pin the keys on the Delivery TypedDict. Telemetry consumers
    (drift-alert dashboard, weekly-digest count, invitation flow's
    success branch) all read these keys by name."""
    from services.mailer import Delivery

    expected = {"to", "subject", "delivered", "reason", "dispatched_at"}
    actual = set(getattr(Delivery, "__annotations__", {}).keys())
    assert actual == expected, (
        f"Delivery TypedDict keys drifted: have {actual}, want {expected}. "
        "Renames here cascade to every dashboard counting deliveries."
    )


# ---------- Skipped path (no SMTP configured) ----------


def test_send_mail_skips_when_smtp_unconfigured(monkeypatch):
    """When `smtp_host` is empty (dev / test), MUST return
    `delivered=False, reason="smtp_not_configured"` — and MUST NOT
    raise. Telemetry pipelines distinguish this branch from real
    SMTP failures.

    A regression that returned `delivered=True` would have invitation
    flows think they sent the welcome email when nothing happened.
    """
    from core.config import get_settings
    from services.mailer import send_mail

    settings = get_settings()
    monkeypatch.setattr(settings, "smtp_host", "", raising=False)
    monkeypatch.setattr(settings, "smtp_user", "", raising=False)

    out = asyncio.run(
        send_mail(
            to="user@example.com",
            subject="test",
            text_body="hi",
        )
    )

    assert out["delivered"] is False, (
        "send_mail returned delivered=True with no SMTP configured. "
        "Caller would think the email landed — silent invitation breakage."
    )
    assert out["reason"] == "smtp_not_configured", (
        f"send_mail's no-config reason drifted to {out['reason']!r}. "
        "Dashboards check for this exact string to render the "
        "'skipped' (vs 'failed') pill."
    )
    assert out["to"] == "user@example.com"
    assert out["subject"] == "test"
    assert "dispatched_at" in out  # timestamp always set


def test_send_mail_skips_when_only_smtp_user_missing(monkeypatch):
    """Partial config — `smtp_host` set but `smtp_user` empty. MUST
    also short-circuit to skipped. The most common dev-env mistake
    is setting host without setting user; a regression that only
    checked host would silently try SMTP without auth and raise."""
    from core.config import get_settings
    from services.mailer import send_mail

    settings = get_settings()
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com", raising=False)
    monkeypatch.setattr(settings, "smtp_user", "", raising=False)

    out = asyncio.run(
        send_mail(
            to="user@example.com",
            subject="test",
            text_body="hi",
        )
    )

    assert out["delivered"] is False
    assert out["reason"] == "smtp_not_configured", (
        "Partial config (host set, user empty) didn't return smtp_not_configured. The check must require BOTH."
    )


# ---------- Failure path (SMTP raises) ----------


def test_send_mail_returns_delivery_on_smtp_failure(monkeypatch):
    """SECURITY/CORRECTNESS pin. When `_send_sync` raises (SMTP
    timeout, auth failure, TLS handshake failed), `send_mail` MUST
    catch it and return `delivered=False, reason="smtp_error:<ExcName>"`.

    A regression that let the exception propagate would:
      * Crash the cron-driven send loop on the first transient
        SMTP blip — no more invitations, no more drift alerts,
        until restart.
      * Skip the per-attempt telemetry write that the caller
        relies on for "this address bounced" dashboards.
    """
    import services.mailer as mailer_mod
    from core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com", raising=False)
    monkeypatch.setattr(settings, "smtp_user", "user", raising=False)

    # Force `_send_sync` (called via asyncio.to_thread) to raise.
    def _raising_send(msg, settings):
        raise TimeoutError("synthetic SMTP timeout")

    monkeypatch.setattr(mailer_mod, "_send_sync", _raising_send)

    out = asyncio.run(
        mailer_mod.send_mail(
            to="user@example.com",
            subject="test",
            text_body="hi",
        )
    )

    assert out["delivered"] is False
    assert out["reason"] is not None and out["reason"].startswith("smtp_error:"), (
        f"send_mail's SMTP-failure reason drifted to {out['reason']!r}; "
        "must start with 'smtp_error:' so dashboards can group these "
        "into the 'real failure' bucket distinct from 'skipped'."
    )
    # Exception name is the discriminator — "TimeoutError" here.
    assert "TimeoutError" in out["reason"]


def test_send_mail_returns_delivery_on_smtp_success(monkeypatch):
    """Happy path — `_send_sync` returns cleanly. MUST report
    `delivered=True, reason=None`. Symmetric to the slack path's
    success branch; pin so a caller's `if delivered:` branch
    keeps working."""
    import services.mailer as mailer_mod
    from core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com", raising=False)
    monkeypatch.setattr(settings, "smtp_user", "user", raising=False)
    monkeypatch.setattr(settings, "smtp_password", "pw", raising=False)
    monkeypatch.setattr(settings, "smtp_port", 587, raising=False)
    monkeypatch.setattr(settings, "email_from", "noreply@example.com", raising=False)

    def _ok_send(msg, settings):
        # Pretend the SMTP send succeeded.
        return None

    monkeypatch.setattr(mailer_mod, "_send_sync", _ok_send)

    out = asyncio.run(
        mailer_mod.send_mail(
            to="user@example.com",
            subject="test",
            text_body="hi",
        )
    )

    assert out["delivered"] is True
    assert out["reason"] is None, (
        f"Happy-path delivery has reason={out['reason']!r}; want None. "
        "A non-None reason on a delivered message would let dashboards "
        "double-count failures."
    )
    assert out["to"] == "user@example.com"
    assert out["subject"] == "test"
    # ISO-8601 timestamp always present.
    assert "T" in out["dispatched_at"], f"dispatched_at isn't ISO-8601: {out['dispatched_at']!r}"


# ---------- Source-level invariants ----------


def test_send_mail_never_raises_source_grep():
    """Defensive source-grep pin. The body MUST wrap the SMTP call
    in try/except and return a Delivery on the except branch — no
    re-raise. A regression that removed the catch would let SMTP
    blips crash callers; we want the failure to surface as a
    `delivered=False` Delivery for telemetry."""
    import services.mailer as mailer_mod

    src = inspect.getsource(mailer_mod.send_mail)
    assert "except Exception" in src, (
        "send_mail no longer has the catch-all except. SMTP failures "
        "would propagate to callers — first transient blip kills the "
        "cron-driven send loop until restart."
    )
    # The except branch returns a Delivery rather than re-raising.
    assert "return Delivery(" in src and "smtp_error:" in src, (
        "send_mail's except branch no longer returns a Delivery with "
        "smtp_error: reason. A re-raise here drifts the contract — "
        "dashboards lose the failure-attribution row."
    )
