"""Unit tests for `services.ops_alerts.send_drift_alert`.

The dispatcher is a thin wrapper around the per-recipient mailer call;
these tests exercise the routing logic + the rendered subject/body
without requiring SMTP to be reachable.

Recipient resolution: the real `_resolve_drift_recipients` reads
`notification_preferences` first then falls back to env. Most tests
in this file want to drive the fallback path directly — they monkey-
patch `ops_alert_emails` and expect those addresses to be used. An
autouse fixture stubs the resolver to read straight from settings
so the tests don't depend on a live DB.
"""

from __future__ import annotations

import logging

import pytest

from services import ops_alerts

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _stub_pref_resolver(monkeypatch):
    """By default, route every test through the env-fallback path.

    Tests that want to exercise the pref-DB path can override this by
    monkeypatching `ops_alerts._resolve_drift_recipients` themselves.
    """

    async def _from_env() -> list[str]:
        return list(ops_alerts.get_settings().ops_alert_emails)

    monkeypatch.setattr(ops_alerts, "_resolve_drift_recipients", _from_env)


# A summary in the shape `services.price_scrapers.run_scraper` produces.
_SUMMARY = {
    "slug": "drifty-province",
    "scraped": 5,
    "matched": 1,
    "unmatched": 4,
    "written": 1,
    "unmatched_sample": [
        "Đèn LED Philips A19",
        "Cửa nhôm Xingfa hệ 55",
        "Lavabo TOTO LW210",
    ],
}


# ---------- Recipient routing ----------


async def test_returns_zero_when_no_recipients_configured(monkeypatch, caplog):
    """No opted-in users + empty OPS_ALERT_EMAILS → no send, no exception."""
    monkeypatch.setattr(ops_alerts.get_settings(), "ops_alert_emails", [])

    # Stub the pref-resolver so the test doesn't hit a live DB. This
    # also pins the contract: when the resolver returns [], the env
    # fallback (also []) wins, and we land in the no-recipients branch.
    async def _no_prefs():
        return []

    monkeypatch.setattr(ops_alerts, "_resolve_drift_recipients", _no_prefs)

    sends: list[dict] = []

    async def _track_send(**kwargs):
        sends.append(kwargs)
        return {"delivered": True, "to": kwargs["to"], "subject": "x", "reason": None}

    monkeypatch.setattr(ops_alerts, "send_mail", _track_send)

    with caplog.at_level(logging.INFO, logger="services.ops_alerts"):
        sent = await ops_alerts.send_drift_alert(slug="x", summary=_SUMMARY)

    assert sent == 0
    assert sends == []
    assert any("no opted-in users and no OPS_ALERT_EMAILS" in r.getMessage() for r in caplog.records)


async def test_dispatches_one_email_per_recipient(monkeypatch):
    """Each address in OPS_ALERT_EMAILS gets its own send_mail call."""
    monkeypatch.setattr(
        ops_alerts.get_settings(),
        "ops_alert_emails",
        ["ops@example.com", "ops-backup@example.com"],
    )

    seen = []

    async def _fake_send(*, to, subject, text_body, html_body=None):
        seen.append({"to": to, "subject": subject, "text_body": text_body})
        return {"delivered": True, "to": to, "subject": subject, "reason": None}

    monkeypatch.setattr(ops_alerts, "send_mail", _fake_send)

    sent = await ops_alerts.send_drift_alert(slug="drifty-province", summary=_SUMMARY)
    assert sent == 2
    assert {s["to"] for s in seen} == {"ops@example.com", "ops-backup@example.com"}


async def test_swallows_individual_send_failures(monkeypatch, caplog):
    """One bad address must NOT deny others their alert."""
    monkeypatch.setattr(
        ops_alerts.get_settings(),
        "ops_alert_emails",
        ["good@example.com", "bad@example.com"],
    )

    async def _fake_send(*, to, subject, text_body, html_body=None):
        if to == "bad@example.com":
            raise RuntimeError("simulated SMTP timeout")
        return {"delivered": True, "to": to, "subject": subject, "reason": None}

    monkeypatch.setattr(ops_alerts, "send_mail", _fake_send)

    with caplog.at_level(logging.WARNING, logger="services.ops_alerts"):
        sent = await ops_alerts.send_drift_alert(slug="x", summary=_SUMMARY)

    # The good one delivers; the bad one is logged + skipped.
    assert sent == 1
    assert any("simulated SMTP timeout" in r.getMessage() for r in caplog.records)


async def test_marks_undelivered_in_log_without_crashing(monkeypatch, caplog):
    """Mailer's `delivered=False` (smtp_unconfigured / bounce) → WARN, no count."""
    monkeypatch.setattr(ops_alerts.get_settings(), "ops_alert_emails", ["ops@example.com"])

    async def _fake_send(**kwargs):
        return {
            "delivered": False,
            "to": kwargs["to"],
            "subject": "x",
            "reason": "smtp_not_configured",
        }

    monkeypatch.setattr(ops_alerts, "send_mail", _fake_send)

    with caplog.at_level(logging.WARNING, logger="services.ops_alerts"):
        sent = await ops_alerts.send_drift_alert(slug="x", summary=_SUMMARY)

    assert sent == 0
    assert any("smtp_not_configured" in r.getMessage() for r in caplog.records)


# ---------- Body rendering ----------


async def test_render_drift_alert_includes_ratio_and_top_samples():
    """The body must surface the actionable bits — ratio, top 5 samples, runbook link."""
    subject, body = ops_alerts._render_drift_alert(slug="drifty-province", summary=_SUMMARY)
    assert "drifty-province" in subject
    assert "80% unmatched" in subject  # 4/5 = 80%

    assert "scraped:    5" in body
    assert "unmatched:  4 (80%)" in body
    # Top 3 samples appear inline.
    assert "Đèn LED Philips A19" in body
    assert "Cửa nhôm Xingfa hệ 55" in body
    # Runbook + admin endpoint pointers — ops needs both to triage.
    assert "GET /api/v1/admin/scraper-runs" in body
    assert "docs/scraper-drift-monitoring.md" in body


async def test_render_caps_sample_names_at_ten():
    """Long unmatched lists must not blow up the email body."""
    summary = dict(_SUMMARY, unmatched_sample=[f"Item {i}" for i in range(25)])
    _, body = ops_alerts._render_drift_alert(slug="x", summary=summary)
    # The first 10 appear; the truncation note mentions the rest.
    assert "Item 0" in body
    assert "Item 9" in body
    assert "Item 10" not in body
    assert "and 15 more" in body


async def test_render_handles_empty_sample_list_without_breaking_layout():
    """Defensive — a high-ratio summary with no sample shouldn't render an empty bullet."""
    summary = dict(_SUMMARY, unmatched_sample=[])
    _, body = ops_alerts._render_drift_alert(slug="x", summary=summary)
    assert "(none — high ratio with no sample is a config bug)" in body


# ---------- Pref-driven recipient resolution ----------


async def test_pref_driven_recipients_take_precedence_over_env(monkeypatch):
    """Opted-in users via NotificationPreference > OPS_ALERT_EMAILS env."""

    # Override the autouse stub to drive the pref-resolver path.
    async def _opted_in():
        return ["alice@example.com", "bob@example.com"]

    monkeypatch.setattr(ops_alerts, "_resolve_drift_recipients", _opted_in)
    # Env var IS set, but should be ignored when prefs return non-empty.
    monkeypatch.setattr(ops_alerts.get_settings(), "ops_alert_emails", ["legacy-ops@example.com"])

    seen: list[str] = []

    async def _track(*, to, subject, text_body, html_body=None):
        seen.append(to)
        return {"delivered": True, "to": to, "subject": subject, "reason": None}

    monkeypatch.setattr(ops_alerts, "send_mail", _track)

    sent = await ops_alerts.send_drift_alert(slug="x", summary=_SUMMARY)
    assert sent == 2
    # Pref opt-ins win; legacy env address gets nothing.
    assert set(seen) == {"alice@example.com", "bob@example.com"}
    assert "legacy-ops@example.com" not in seen


async def test_resolver_falls_back_to_env_when_no_users_opted_in(monkeypatch):
    """Resolver itself: empty `notification_preferences` → use OPS_ALERT_EMAILS.

    Patches the SQLA session factory so the resolver sees no rows;
    asserts the env list is what comes out the other end. This is
    the legacy-compat path — without it, every existing prod deploy
    that hasn't migrated to the prefs UI would silently stop alerting.
    """
    from db import session as db_session

    class _EmptyResultSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def execute(self, *_a, **_k):
            from unittest.mock import MagicMock

            r = MagicMock()
            r.scalars.return_value.all.return_value = []
            return r

    monkeypatch.setattr(db_session, "AdminSessionFactory", lambda: _EmptyResultSession())
    monkeypatch.setattr(ops_alerts.get_settings(), "ops_alert_emails", ["legacy-ops@example.com"])

    recipients = await ops_alerts._resolve_drift_recipients()
    assert recipients == ["legacy-ops@example.com"]
