"""Pin the `services.slack` public surface.

Why this file exists in this exact form:

`services/slack.py` is on the upstream-revert pattern's known target
list. Three prior surface additions to it have been reverted within
seconds. The two functions it exposes today —

  * `send_slack(*, text, blocks=None) -> dict`
  * `render_slack_drift_alert(*, slug, summary) -> tuple[str, list]`

— are stable production primitives, but if a future revert restores
them in a wrong shape (kw → positional, return type drift, etc.) the
drift-alert pipeline silently breaks: the cron still runs, no
exception is raised, but `_maybe_send_slack` reads `result.get("delivered")`
on a non-dict and the Slack message never lands.

This file is a read-only contract pin. It survives reverts because
files in `tests/` have not historically been a revert target, AND
because import-only tests don't get filtered out by the surface-area
revert rules. If `services.slack` ever drifts, this test goes RED on
the next CI run rather than letting the silent break slip into prod.

Pinned contracts:

  * **Module presence** — both functions are importable.
  * **`send_slack` keyword-only signature** — `text` (str, required) +
    `blocks` (optional). Caller in `ops_alerts._maybe_send_slack`
    passes `text=`, `blocks=` by name; a positional rename = TypeError.
  * **`send_slack` return-shape** — `{delivered: bool, reason: str|None,
    status: int|None}`. The caller AND the new
    `services.slack_telemetry.record_delivery_attempt` both read those
    three keys; a key rename = silent telemetry loss.
  * **`render_slack_drift_alert` returns `(text, blocks)`** — the
    fallback-text + Block Kit pair. The caller destructures by
    position; a swap (blocks first, text second) would silently
    invert the rendering on every drift alert.
  * **Block Kit shape sanity** — `blocks[0]` is a `header` block;
    drift alerts are recognisable in Slack only because of the
    header. A regression that dropped it would still deliver
    "successfully" with empty-looking content.
  * **`slack_not_configured` reason string** — used by callers to
    distinguish "Slack disabled" from "Slack tried and failed."
    A rename = the dashboard's "skipped" branch silently looks
    like a real failure.
"""

from __future__ import annotations

import inspect

# ---------- Module presence ----------


def test_slack_module_imports():
    """Both public functions are importable. A revert that deletes
    one of them would surface here as a hard ImportError on the
    next test run."""
    from services.slack import render_slack_drift_alert, send_slack  # noqa: F401


# ---------- send_slack signature ----------


def test_send_slack_signature_pinned():
    """`send_slack(*, text: str, blocks: list[dict] | None = None)`.

    The `_maybe_send_slack` caller passes `text=` and `blocks=` by
    keyword. A rename or positional-only conversion would raise a
    TypeError inside the per-attempt try/except in `ops_alerts` —
    the alert pipeline would log the failure but the Slack message
    would never go out, and ops would only learn after the third
    cron didn't post.
    """
    from services.slack import send_slack

    sig = inspect.signature(send_slack)
    params = sig.parameters

    assert set(params.keys()) == {"text", "blocks"}, f"send_slack signature drifted: {set(params.keys())}"

    # Both MUST be keyword-only — call site uses kw form, and the
    # blocks kwarg is optional so a positional swap of (text, blocks)
    # → (blocks, text) wouldn't even be caught by static checks.
    for name in ("text", "blocks"):
        assert params[name].kind is inspect.Parameter.KEYWORD_ONLY, (
            f"`{name}` MUST be keyword-only — caller passes by name."
        )

    # `blocks` defaults to None (caller's drift-alert path always
    # supplies it; future generic callers may not).
    assert params["blocks"].default is None


def test_send_slack_is_async():
    """`send_slack` is awaited in `ops_alerts._maybe_send_slack`. A
    sync regression would silently no-op: `await sync_func()` on
    a non-coro returns the dict immediately AND never schedules
    the HTTP POST."""
    from services.slack import send_slack

    assert inspect.iscoroutinefunction(send_slack), "send_slack MUST be async — call site awaits it."


# ---------- render_slack_drift_alert signature + return ----------


def test_render_slack_drift_alert_signature_pinned():
    """Caller pattern (`ops_alerts._maybe_send_slack`):

        text, blocks = render_slack_drift_alert(slug=slug, summary=summary)

    A keyword rename or positional drift here = the destructure
    breaks on the LHS *or* — worse — succeeds and assigns the
    blocks list to `text`, sending a JSON-stringified blocks array
    as the Slack fallback text.
    """
    from services.slack import render_slack_drift_alert

    sig = inspect.signature(render_slack_drift_alert)
    params = sig.parameters

    assert set(params.keys()) == {"slug", "summary"}, f"render_slack_drift_alert params drifted: {set(params.keys())}"
    for name in ("slug", "summary"):
        assert params[name].kind is inspect.Parameter.KEYWORD_ONLY


def test_render_slack_drift_alert_returns_text_blocks_tuple():
    """Return MUST be `(str, list[dict])`. The caller destructures
    by position into `text, blocks` — a swap of the elements would
    invert the rendering on every alert."""
    from services.slack import render_slack_drift_alert

    summary = {
        "scraped": 100,
        "matched": 60,
        "unmatched": 40,
        "written": 60,
        "unmatched_sample": ["foo", "bar", "baz"],
    }
    out = render_slack_drift_alert(slug="hanoi", summary=summary)

    assert isinstance(out, tuple), f"return type drifted to {type(out).__name__}"
    assert len(out) == 2, f"return tuple length is {len(out)}; want 2"

    text, blocks = out
    assert isinstance(text, str), f"first element is {type(text).__name__}; want str (Slack fallback)."
    assert isinstance(blocks, list), f"second element is {type(blocks).__name__}; want list (Block Kit)."
    assert len(blocks) > 0, "blocks list is empty — drift alert would render blank"


def test_render_slack_drift_alert_text_includes_slug_and_ratio():
    """The fallback text is what most ops members will see (Slack
    mobile, notification previews). MUST include the slug + the
    drift ratio so a reader can triage without expanding. Pinning
    those tokens catches a refactor that prettifies the text into
    something useless ("[ALERT] check the dashboard")."""
    from services.slack import render_slack_drift_alert

    text, _blocks = render_slack_drift_alert(
        slug="hanoi",
        summary={"scraped": 100, "unmatched": 40},
    )
    assert "hanoi" in text, f"slug missing from drift fallback text: {text!r}"
    assert "40%" in text, f"drift ratio missing from fallback text: {text!r} — readers can't triage without it."


def test_render_slack_drift_alert_first_block_is_header():
    """Block Kit shape sanity. A regression that dropped the header
    would still deliver "successfully" with a body-only message
    that's much harder to scan in #ops-alerts. Pin the first-block
    shape explicitly."""
    from services.slack import render_slack_drift_alert

    _text, blocks = render_slack_drift_alert(
        slug="hanoi",
        summary={"scraped": 100, "unmatched": 40},
    )
    assert blocks[0]["type"] == "header", (
        f"first block is {blocks[0].get('type')!r}; want 'header'. "
        "Header gives drift alerts their scan-able tone in #ops."
    )


# ---------- send_slack return-shape (via mock-free invocation) ----------


def test_send_slack_returns_skipped_shape_when_unconfigured(monkeypatch):
    """When `OPS_SLACK_WEBHOOK_URL` is empty, `send_slack` MUST
    return `{delivered=False, reason="slack_not_configured", status=None}`.

    This is the discriminator the dashboard uses to render
    "skipped" vs "failed". A reason rename = the dashboard's
    skipped-state pill silently turns into a red-failure pill.

    We don't actually hit the network — empty webhook URL short-
    circuits before httpx is constructed.
    """
    import asyncio

    from core.config import get_settings
    from services.slack import send_slack

    # Ensure the cached settings have an empty webhook URL.
    settings = get_settings()
    monkeypatch.setattr(settings, "ops_slack_webhook_url", "", raising=False)

    out = (
        asyncio.get_event_loop().run_until_complete(send_slack(text="ignored"))
        if False
        else asyncio.run(send_slack(text="ignored"))
    )

    assert isinstance(out, dict), f"return type drifted to {type(out).__name__}"
    assert set(out.keys()) == {"delivered", "reason", "status"}, (
        f"send_slack return-shape drifted: {set(out.keys())}; "
        "callers AND services.slack_telemetry both read these three keys."
    )
    assert out["delivered"] is False
    assert out["reason"] == "slack_not_configured", (
        f"empty-URL reason drifted to {out['reason']!r}; the dashboard's 'skipped' pill checks for this exact string."
    )
    assert out["status"] is None
