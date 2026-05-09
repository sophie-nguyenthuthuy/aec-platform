"""Unit tests for `services.slack.send_slack` + the drift-block renderer.

The webhook itself is mocked at the httpx level — these tests pin the
delivery contract (`{delivered, reason, status}`) and the Block-Kit
rendering shape, without touching a real Slack workspace.
"""

from __future__ import annotations

import pytest

from services import slack as slack_module

pytestmark = pytest.mark.asyncio


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


# ---------- send_slack ----------


async def test_send_slack_returns_skip_reason_when_unconfigured(monkeypatch):
    """Empty `OPS_SLACK_WEBHOOK_URL` → silent no-op with structured reason."""
    monkeypatch.setattr(slack_module.get_settings(), "ops_slack_webhook_url", None)

    result = await slack_module.send_slack(text="hello")

    assert result == {
        "delivered": False,
        "reason": "slack_not_configured",
        "status": None,
    }


async def test_send_slack_posts_to_configured_webhook(monkeypatch):
    """Happy path: Slack returns 200 → delivered=True."""
    monkeypatch.setattr(
        slack_module.get_settings(),
        "ops_slack_webhook_url",
        "https://hooks.slack.com/services/AAA/BBB/CCC",
    )

    posted: list[dict] = []

    class _FakeResponse:
        status_code = 200
        text = "ok"
        reason_phrase = "OK"

    class _FakeClient:
        def __init__(self, *_, timeout=None):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def post(self, url, *, json):
            posted.append({"url": url, "json": json})
            return _FakeResponse()

    monkeypatch.setattr(slack_module.httpx, "AsyncClient", _FakeClient)

    result = await slack_module.send_slack(
        text="warning", blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": "x"}}]
    )

    assert result == {"delivered": True, "reason": None, "status": 200}
    assert len(posted) == 1
    body = posted[0]["json"]
    assert body["text"] == "warning"
    assert "blocks" in body


async def test_send_slack_returns_status_on_4xx(monkeypatch):
    """Slack 400 (invalid blocks, bad URL) surfaces as a structured failure."""
    monkeypatch.setattr(
        slack_module.get_settings(),
        "ops_slack_webhook_url",
        "https://hooks.slack.com/services/AAA/BBB/CCC",
    )

    class _BadResponse:
        status_code = 400
        text = "invalid_blocks: missing_text"
        reason_phrase = "Bad Request"

    class _FakeClient:
        def __init__(self, *_, timeout=None):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def post(self, url, *, json):
            return _BadResponse()

    monkeypatch.setattr(slack_module.httpx, "AsyncClient", _FakeClient)

    result = await slack_module.send_slack(text="x")

    assert result["delivered"] is False
    assert result["reason"] == "slack_http_400"
    assert result["status"] == 400


async def test_send_slack_swallows_transport_errors(monkeypatch):
    """Slack outage / DNS failure → delivered=False with transport reason."""
    monkeypatch.setattr(
        slack_module.get_settings(),
        "ops_slack_webhook_url",
        "https://hooks.slack.com/services/AAA/BBB/CCC",
    )

    import httpx

    class _FailingClient:
        def __init__(self, *_, timeout=None):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def post(self, *_a, **_kw):
            raise httpx.ConnectError("DNS lookup failed")

    monkeypatch.setattr(slack_module.httpx, "AsyncClient", _FailingClient)

    result = await slack_module.send_slack(text="x")

    assert result["delivered"] is False
    assert result["reason"].startswith("transport:")
    assert result["status"] is None


# ---------- render_slack_drift_alert ----------


async def test_render_drift_alert_block_kit_shape():
    """Pin the basic Block Kit layout so a future tweak doesn't silently
    drop the slug-in-header or ratio-in-fields."""
    text, blocks = slack_module.render_slack_drift_alert(slug="drifty", summary=_SUMMARY)

    # Fallback text always carries the slug + ratio.
    assert "drifty" in text
    assert "80%" in text  # 4/5

    # Header block is plain_text with the slug.
    header = blocks[0]
    assert header["type"] == "header"
    assert "drifty" in header["text"]["text"]

    # Fields block has 4 entries: Scraped, Matched, Unmatched, Written.
    fields_block = blocks[1]
    assert fields_block["type"] == "section"
    field_texts = [f["text"] for f in fields_block["fields"]]
    assert any("Scraped" in t for t in field_texts)
    assert any("Unmatched" in t and "(80%)" in t for t in field_texts)


async def test_render_caps_sample_at_five_inline():
    """Long unmatched lists shouldn't blow up the Slack message."""
    summary = dict(_SUMMARY, unmatched_sample=[f"Item {i}" for i in range(20)])
    _, blocks = slack_module.render_slack_drift_alert(slug="x", summary=summary)

    # The sample-text section is the third block.
    sample_block = blocks[2]
    body = sample_block["text"]["text"]
    assert "Item 0" in body
    assert "Item 4" in body
    assert "Item 5" not in body  # capped at 5
    assert "and 15 more" in body


async def test_render_handles_empty_sample_list():
    """A high-ratio summary with no sample shouldn't render as an empty
    bullet list — show the placeholder instead."""
    summary = dict(_SUMMARY, unmatched_sample=[])
    _, blocks = slack_module.render_slack_drift_alert(slug="x", summary=summary)

    sample_block = blocks[2]
    assert "no sample" in sample_block["text"]["text"].lower()
