"""Snapshot tests for transactional email rendering.

What this catches that runtime tests don't
------------------------------------------
The existing `test_invitation_email.py` etc. assert "did `send_mail`
get called with `to=...`" — they DON'T diff the rendered HTML/text
against an expected blob. Refactor a `<p>` to a `<div>`, drop a
variable from the template, accidentally render `{role}` as the
literal `Role.ADMIN` enum repr instead of `"admin"` — none of those
trip the existing tests, but all of them ship malformed email to
real users.

How it works
------------
Each test renders one transactional template and diff-checks the
result against a committed file in `tests/email_snapshots/`. The
snapshot files are plain text (text/HTML — no JSON wrapper) so a
reviewer can read them directly in a PR diff.

When the change is intentional (you DID just refactor the template),
regenerate the snapshots:

    SNAPSHOT_UPDATE=1 pytest tests/test_email_templates_snapshot.py

…then commit the updated `*.snap` files alongside the template
change. A reviewer scans the snap diff for the same regression
shapes the runtime tests miss (variable rename, layout break,
encoding mishap).

Why not Jinja
-------------
Today the templates are inline f-strings in `services/*.py`. The
team plan is to move them to Jinja2 once we have proper i18n on the
api side; this test layer doesn't care which it is — it diffs the
rendered string. When templates move to Jinja, only the snapshot
contents change (whitespace might shift); the test code is reusable.

What's snapshotted
------------------
- The invitation email (vi-VN, with + without an inviter name).
- The RFQ dispatch email (English-Vietnamese mix; the supplier-
  facing template).
- The codeguard quota threshold-warning email (vi-VN; both the 80%
  warn and 95% critical variants).

Each path's full text/HTML body, plus the subject line.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

import pytest

# Snapshots live next to the test in a sibling directory. Keeping
# them in the test tree (rather than inline in the test file as
# triple-quoted strings) means a reviewer can open the file and
# scan it as plain HTML/text — no parsing-around-Python-quoting.
_SNAP_DIR = Path(__file__).parent / "email_snapshots"
_UPDATE = os.environ.get("SNAPSHOT_UPDATE") == "1"


def _check_snapshot(name: str, actual: str) -> None:
    """Compare `actual` against the committed snapshot file.

    On `SNAPSHOT_UPDATE=1`: write `actual` to disk and pass.
    Otherwise: read the snapshot and assertEqual; on mismatch, the
    test failure includes a diff hint pointing at how to regenerate.
    """
    path = _SNAP_DIR / name
    if _UPDATE:
        _SNAP_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(actual, encoding="utf-8")
        return
    if not path.exists():
        pytest.fail(
            f"Snapshot {path.name} doesn't exist yet. Run "
            f"`SNAPSHOT_UPDATE=1 pytest tests/test_email_templates_snapshot.py` "
            f"to create it, then commit the file."
        )
    expected = path.read_text(encoding="utf-8")
    if expected != actual:
        # Surface a focused diff hint. The full diff is big — let
        # pytest's default report show it via the != formatter, but
        # tell the reader how to regenerate intentionally.
        pytest.fail(
            f"Email template '{name}' rendered differently from snapshot.\n"
            f"  Snapshot path: {path}\n"
            f"  If this change is intentional, regenerate with:\n"
            f"      SNAPSHOT_UPDATE=1 pytest tests/test_email_templates_snapshot.py::<test>\n"
            f"  …then review the snap diff in your PR alongside the template change.\n\n"
            f"--- expected (first 400 chars)\n{expected[:400]}\n"
            f"--- actual (first 400 chars)\n{actual[:400]}"
        )


# ---------- Invitation email ----------


@pytest.mark.asyncio
async def test_invitation_email_with_inviter_name():
    """Invitation email when the inviter has a display name set.

    Captures both subject + text + HTML by mocking out `send_mail`
    and reading what it was called with. Pinning all three together
    guarantees they stay in sync — a regression that updated the
    HTML but forgot the text fallback would surface here.
    """
    from services import invitation_email

    captured: dict[str, str] = {}

    async def _capture(*, to: str, subject: str, text_body: str, html_body: str | None = None):
        captured["to"] = to
        captured["subject"] = subject
        captured["text"] = text_body
        captured["html"] = html_body or ""
        return {
            "to": to,
            "subject": subject,
            "delivered": True,
            "reason": "captured",
            "dispatched_at": "2026-05-03T12:00:00Z",
        }

    with patch.object(invitation_email, "send_mail", new=_capture):
        await invitation_email.send_invitation_email(
            to="invitee@example.com",
            organization_name="Marina Tower JV",
            role="member",
            accept_url="https://app.aec.local/invitations/abc123",
            invited_by_name="Alice Nguyen",
        )

    rendered = f"SUBJECT: {captured['subject']}\n---TEXT---\n{captured['text']}\n---HTML---\n{captured['html']}\n"
    _check_snapshot("invitation_with_inviter.snap", rendered)


@pytest.mark.asyncio
async def test_invitation_email_without_inviter_name():
    """Inviter name is None — falls back to "Quản trị viên" (admin).

    Pin the fallback explicitly. A regression that rendered the
    literal string `"None"` (or worse, `None.title()` crashing)
    would not show up in the with-name path above.
    """
    from services import invitation_email

    captured: dict[str, str] = {}

    async def _capture(*, to: str, subject: str, text_body: str, html_body: str | None = None):
        captured.update({"subject": subject, "text": text_body, "html": html_body or ""})
        return {
            "to": to,
            "subject": subject,
            "delivered": True,
            "reason": "captured",
            "dispatched_at": "2026-05-03T12:00:00Z",
        }

    with patch.object(invitation_email, "send_mail", new=_capture):
        await invitation_email.send_invitation_email(
            to="invitee@example.com",
            organization_name="Marina Tower JV",
            role="admin",
            accept_url="https://app.aec.local/invitations/abc123",
            invited_by_name=None,
        )

    rendered = f"SUBJECT: {captured['subject']}\n---TEXT---\n{captured['text']}\n---HTML---\n{captured['html']}\n"
    _check_snapshot("invitation_without_inviter.snap", rendered)


# ---------- RFQ dispatch email ----------


def test_rfq_dispatch_email_render():
    """Snapshot the supplier-facing RFQ email.

    `_render` is a pure function — no async, no DB, no mailer. We
    construct light dataclass-shaped fakes that supply just the
    attributes the renderer reads. This pins the supplier copy
    that lands in their inbox; a regression would land badly because
    suppliers see this BEFORE they ever interact with the platform.
    """
    from services.rfq_dispatch import _render

    # Ad-hoc fakes — `_render` only reads these specific attributes.
    # Going through the real models would force us to import + stand
    # up far more orm machinery than we need for a string-rendering
    # test.
    rfq = type(
        "Rfq",
        (),
        {
            "id": UUID("11111111-1111-1111-1111-111111111111"),
            "deadline": __import__("datetime").date(2026, 6, 15),
        },
    )()
    estimate = type("Estimate", (), {"name": "Marina Tower curtain wall"})()
    supplier = type("Supplier", (), {"name": "Saigon Aluminum Co."})()
    boq_digest = "  - [AL-001] Aluminum frame profile — 1200 m\n  - [GL-101] Tempered glass 12mm — 850 m²"
    response_url = "https://app.aec.local/rfq/respond?t=token-here"

    subject, body = _render(
        rfq=rfq,
        estimate=estimate,
        supplier=supplier,
        boq_digest=boq_digest,
        response_url=response_url,
    )
    rendered = f"SUBJECT: {subject}\n---BODY---\n{body}"
    _check_snapshot("rfq_dispatch.snap", rendered)


def test_rfq_dispatch_email_render_no_estimate():
    """`estimate=None` falls back to "(no linked estimate)" in copy.

    Pinning the fallback specifically — a regression that crashed
    on `estimate.name` (vs the current `None`-guard) would only
    surface when a user actually dispatches against a no-estimate
    RFQ, which isn't the dominant path.
    """
    from services.rfq_dispatch import _render

    rfq = type(
        "Rfq",
        (),
        {
            "id": UUID("22222222-2222-2222-2222-222222222222"),
            "deadline": None,
        },
    )()
    supplier = type("Supplier", (), {"name": "Test Supplier"})()

    subject, body = _render(
        rfq=rfq,
        estimate=None,
        supplier=supplier,
        boq_digest="(estimate had no BOQ items)",
        response_url="https://app.aec.local/rfq/respond?t=tok",
    )
    rendered = f"SUBJECT: {subject}\n---BODY---\n{body}"
    _check_snapshot("rfq_dispatch_no_estimate.snap", rendered)


# ---------- CodeGuard quota threshold email ----------
#
# Two variants — 80% (warn tone) and 95% (critical tone). Different
# subject + headline + intro. A regression that swapped the two
# tones would change the urgency conveyed to finance/admin without
# triggering any unit test.


def test_quota_threshold_email_warn_at_80_percent(monkeypatch):
    """The 80% threshold email — warn tone, "approaching cap"."""
    from services import codeguard_quotas

    # Pin web_base_url so the rendered href is deterministic.
    monkeypatch.setattr(codeguard_quotas, "_quota_page_url", lambda: "https://app.aec.local/codeguard/quota")

    subject, text_body, html_body = codeguard_quotas._render_threshold_email(
        dimension="input",
        threshold=80,
        used=800_000,
        limit=1_000_000,
        percent=80.0,
    )
    rendered = f"SUBJECT: {subject}\n---TEXT---\n{text_body}\n---HTML---\n{html_body}\n"
    _check_snapshot("quota_threshold_warn_80.snap", rendered)


def test_quota_threshold_email_critical_at_95_percent(monkeypatch):
    """The 95% threshold email — critical tone, "imminent 429"."""
    from services import codeguard_quotas

    monkeypatch.setattr(codeguard_quotas, "_quota_page_url", lambda: "https://app.aec.local/codeguard/quota")

    subject, text_body, html_body = codeguard_quotas._render_threshold_email(
        dimension="output",
        threshold=95,
        used=475_000,
        limit=500_000,
        percent=95.0,
    )
    rendered = f"SUBJECT: {subject}\n---TEXT---\n{text_body}\n---HTML---\n{html_body}\n"
    _check_snapshot("quota_threshold_critical_95.snap", rendered)
