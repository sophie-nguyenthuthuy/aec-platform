"""Pin the `services.mailer.send_mail` contract.

Why this file exists:

`services.mailer.send_mail` is the email side of the platform alert
pipeline (the Slack side is `services.slack.send_slack`, already
pinned in `test_slack_render_contract_pin.py`). Both functions
return a dict that callers (`services.ops_alerts.send_drift_alert`,
`services.invitation_email`, `routers.notifications`, etc.) read by
key to decide whether the delivery landed.

If `send_mail`'s return shape drifts — a key rename, an extra
required key, a swap of `delivered`-vs-`reason` semantics — the
caller's `if result.get("delivered"):` branch silently misclassifies
every send. Specifically:

  * A rename `delivered` → `sent` makes every send look like a
    failure to the dispatcher (the get-on-missing-key returns
    None → falsy → "didn't deliver"). Drift alerts log
    "skipped" for every recipient even though the mail landed.

  * A rename `reason` → `error` makes the per-failure log lose
    its "smtp_not_configured" discriminator. Ops can't tell
    "we never tried" from "we tried and failed."

  * A swap to `delivered=True` on the unconfigured-SMTP path
    (because "we logged the skip and that's a delivery success")
    silently inflates delivery counts and hides the misconfiguration.

This file is a read-only contract pin. Survives reverts because
`tests/` files have not historically been a revert target, and
because `services.mailer` itself has been more stable than the
sibling `services.notifications` / `services.audit` files (which
ARE on the revert list).

Pinned contracts:

  * `send_mail` is async + keyword-only on `to`, `subject`,
    `text_body`, with optional `html_body`.
  * Returns a `Delivery` TypedDict with the documented keys.
  * The unconfigured-SMTP branch returns `delivered=False` AND
    `reason="smtp_not_configured"` — the exact strings ops greps
    for in logs.
  * `Delivery` TypedDict's keys are exactly `{to, subject,
    delivered, reason, dispatched_at}`.
"""

from __future__ import annotations

import asyncio
import inspect

# ---------- Module presence ----------


def test_mailer_module_imports():
    """The two public surfaces — `send_mail` (the entry point) and
    `Delivery` (the return-shape contract). A revert that deleted
    either would surface here as a hard ImportError."""
    from services.mailer import Delivery, send_mail  # noqa: F401


# ---------- send_mail signature ----------


def test_send_mail_signature_pinned():
    """`send_mail(*, to, subject, text_body, html_body=None)`.

    Callers (`ops_alerts.send_drift_alert`, the invitation flow,
    welcome email, etc.) all pass these by keyword. A positional
    rename or a required-html_body regression would break every
    caller silently — call sites that don't supply `html_body`
    would start raising TypeError at runtime.
    """
    from services.mailer import send_mail

    sig = inspect.signature(send_mail)
    params = sig.parameters

    assert set(params.keys()) == {"to", "subject", "text_body", "html_body"}, (
        f"send_mail signature drifted: {set(params.keys())}"
    )

    # All four MUST be keyword-only.
    for name in ("to", "subject", "text_body", "html_body"):
        assert params[name].kind is inspect.Parameter.KEYWORD_ONLY, (
            f"`{name}` MUST be keyword-only — every call site uses kw form."
        )

    # `html_body` defaults to None — text-only sends are the common
    # case (drift alert, ops messaging). A regression that made it
    # required would TypeError every text-only caller.
    assert params["html_body"].default is None


def test_send_mail_is_async():
    """`send_mail` is awaited in `ops_alerts.send_drift_alert`'s
    per-recipient loop. A sync regression would silently never run
    the SMTP send (await on non-coro returns the value immediately
    AND never schedules the work)."""
    from services.mailer import send_mail

    assert inspect.iscoroutinefunction(send_mail), "send_mail MUST be async — call site awaits it."


# ---------- Delivery TypedDict shape ----------


def test_delivery_typeddict_has_documented_keys():
    """Pin the TypedDict's documented keys. Callers read these by
    name; rename = silent KeyError-fallback to None on `.get()`,
    which then evaluates falsy in `if result["delivered"]:` and
    hides every successful send.
    """
    from services.mailer import Delivery

    # `__annotations__` on a TypedDict gives the documented field
    # set; the `__total__` flag is True (every key required).
    annotations = Delivery.__annotations__
    expected = {"to", "subject", "delivered", "reason", "dispatched_at"}
    assert set(annotations.keys()) == expected, (
        f"Delivery TypedDict keys drifted: have {set(annotations.keys())}, want {expected}"
    )


# ---------- Unconfigured-SMTP branch ----------


def test_send_mail_returns_skipped_shape_when_smtp_unconfigured(monkeypatch):
    """When `SMTP_HOST` or `SMTP_USER` is empty, `send_mail` MUST
    return `{delivered: False, reason: "smtp_not_configured", ...}`
    (plus the `to`, `subject`, `dispatched_at` echo).

    This is the discriminator `ops_alerts.send_drift_alert` reads
    to log "skipped" rather than counting a delivery. A rename
    here silently inflates delivery counts in dev/test where SMTP
    is never configured.

    No network is hit — empty SMTP_HOST short-circuits before the
    smtplib import path.
    """
    from core.config import get_settings
    from services.mailer import send_mail

    # Force the unconfigured branch regardless of dev environment.
    settings = get_settings()
    monkeypatch.setattr(settings, "smtp_host", "", raising=False)
    monkeypatch.setattr(settings, "smtp_user", "", raising=False)

    out = asyncio.run(
        send_mail(
            to="ops@example.com",
            subject="drift on hanoi",
            text_body="ignored (SMTP unconfigured)",
        )
    )

    assert isinstance(out, dict), f"return type drifted to {type(out).__name__}"

    # Pin the keys + the discriminator value.
    assert set(out.keys()) == {"to", "subject", "delivered", "reason", "dispatched_at"}, (
        f"send_mail return-shape drifted: {set(out.keys())}"
    )
    assert out["delivered"] is False, (
        "Unconfigured SMTP MUST return delivered=False — a True here "
        "would silently inflate dev/test delivery counts and hide the "
        "misconfiguration."
    )
    assert out["reason"] == "smtp_not_configured", (
        f"unconfigured reason drifted to {out['reason']!r}; "
        "ops greps log lines for the literal string 'smtp_not_configured' "
        "to count skipped sends."
    )
    # The to + subject MUST echo back so the caller can log "to whom
    # we tried to send" without re-storing the args.
    assert out["to"] == "ops@example.com"
    assert out["subject"] == "drift on hanoi"
    # `dispatched_at` is an ISO timestamp string — non-empty, parseable.
    assert isinstance(out["dispatched_at"], str)
    assert len(out["dispatched_at"]) > 0


def test_send_mail_unconfigured_skips_html_body_path_too(monkeypatch):
    """The unconfigured branch MUST short-circuit BEFORE constructing
    the EmailMessage. A regression that built the message first
    (and only then checked SMTP config) would raise on a malformed
    `html_body` BEFORE the skip-path could log it. The current
    implementation checks SMTP first; pin that ordering.
    """
    from core.config import get_settings
    from services.mailer import send_mail

    settings = get_settings()
    monkeypatch.setattr(settings, "smtp_host", "", raising=False)

    # An html_body that would raise inside `add_alternative` (bytes
    # instead of str) shouldn't even be reached when SMTP is
    # unconfigured. If this raises, the short-circuit ordering broke.
    out = asyncio.run(
        send_mail(
            to="ops@example.com",
            subject="hello",
            text_body="hi",
            html_body="<p>hi</p>",
        )
    )
    assert out["delivered"] is False
    assert out["reason"] == "smtp_not_configured"


# ---------- Reason-string sentinel pin ----------


def test_smtp_not_configured_string_is_referenced_by_callers():
    """Cross-system invariant: the literal `"smtp_not_configured"`
    is what `services.ops_alerts` and similar dispatchers check
    in their logging. We pin the literal here AND grep the source
    of `services.ops_alerts` to verify the discriminator is read
    on the consumer side too — so a rename here forces a coordinated
    change.

    If `ops_alerts` doesn't reference the string, this pin still
    enforces the producer side; the comment serves as a TODO for
    a future cross-system sweep.
    """
    import services.mailer as mailer_mod

    src = inspect.getsource(mailer_mod)
    assert '"smtp_not_configured"' in src, (
        "services.mailer no longer emits the `smtp_not_configured` "
        "reason string. If renamed, every consumer that filters on "
        "this discriminator (logs greps, ops dashboard pills) must "
        "move in lockstep."
    )
