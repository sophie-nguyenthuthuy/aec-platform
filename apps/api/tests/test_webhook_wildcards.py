"""Webhook event wildcard subscriptions (cycle U2).

Pinned seams:
  1. `_wildcard_candidates(event_type)` produces the set of wildcard
     patterns that would match the supplied event. Walks segment
     prefixes from most-specific to least.
  2. The schema validator accepts `<prefix>.*` and rejects malformed
     wildcards (`*`, `*.foo`, `costpulse.*.*`).
  3. `enqueue_event` matches subscriptions whose `event_types`
     contain a wildcard covering the fired event — pin via the
     SQL bound params.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
from uuid import UUID

import pytest

pytestmark = pytest.mark.asyncio


ORG_ID = UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")


# ---------- _wildcard_candidates ----------


def test_wildcard_candidates_for_three_segment_event():
    """`costpulse.estimate.approve` produces both
    `costpulse.estimate.*` and `costpulse.*` — most-specific first.
    Pin the order so the test failure message is stable."""
    from services.webhooks import _wildcard_candidates

    out = _wildcard_candidates("costpulse.estimate.approve")
    assert out == ["costpulse.estimate.*", "costpulse.*"]


def test_wildcard_candidates_for_two_segment_event():
    """`webhook.test` produces only `webhook.*`."""
    from services.webhooks import _wildcard_candidates

    out = _wildcard_candidates("webhook.test")
    assert out == ["webhook.*"]


def test_wildcard_candidates_for_single_segment_event():
    """A type with no dot has no wildcards that match it. The
    matcher falls back to the empty array; the SQL OR clause
    short-circuits via the `&&` operator on an empty rhs."""
    from services.webhooks import _wildcard_candidates

    assert _wildcard_candidates("unstructured") == []


# ---------- Schema validator ----------


def test_schema_accepts_module_wildcard():
    """Partner subscribing to `costpulse.*` is the canonical wildcard
    use case. Pin the validator accepts it."""
    from schemas.webhooks import WebhookSubscriptionCreate

    out = WebhookSubscriptionCreate(
        url="https://example.com/hook",
        event_types=["costpulse.*"],
    )
    assert out.event_types == ["costpulse.*"]


def test_schema_accepts_multi_segment_wildcard():
    """`costpulse.estimate.*` narrows the wildcard to one resource."""
    from schemas.webhooks import WebhookSubscriptionCreate

    out = WebhookSubscriptionCreate(
        url="https://example.com/hook",
        event_types=["costpulse.estimate.*"],
    )
    assert out.event_types == ["costpulse.estimate.*"]


def test_schema_rejects_bare_asterisk():
    """`*` alone (no module prefix) is too permissive — partner
    likely meant empty array. Reject so a typo doesn't accidentally
    subscribe to everything."""
    import pydantic

    from schemas.webhooks import WebhookSubscriptionCreate

    with pytest.raises(pydantic.ValidationError):
        WebhookSubscriptionCreate(
            url="https://example.com/hook",
            event_types=["*"],
        )


def test_schema_rejects_embedded_asterisk():
    """`costpulse.*.approve` mid-segment wildcards aren't supported.
    Reject so the matcher doesn't have to handle the case."""
    import pydantic

    from schemas.webhooks import WebhookSubscriptionCreate

    with pytest.raises(pydantic.ValidationError):
        WebhookSubscriptionCreate(
            url="https://example.com/hook",
            event_types=["costpulse.*.approve"],
        )


def test_schema_rejects_wildcard_without_terminal_dot():
    """`costpulse*` (no dot before `*`) is malformed — `costpulse.*`
    is the only valid form. Reject so the matching rule stays
    simple."""
    import pydantic

    from schemas.webhooks import WebhookSubscriptionCreate

    with pytest.raises(pydantic.ValidationError):
        WebhookSubscriptionCreate(
            url="https://example.com/hook",
            event_types=["costpulse*"],
        )


def test_schema_accepts_mix_of_literal_and_wildcard():
    """A subscription can carry both literal slugs AND wildcards.
    Pin so a refactor that special-cases one form doesn't break
    the mixed case (which is operationally common)."""
    from schemas.webhooks import WebhookSubscriptionCreate

    out = WebhookSubscriptionCreate(
        url="https://example.com/hook",
        event_types=["pulse.change_order.approve", "costpulse.*"],
    )
    assert out.event_types == ["pulse.change_order.approve", "costpulse.*"]


# ---------- enqueue_event SQL bound params ----------


class _FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, dict[str, Any]]] = []
        self._results: list[Any] = []

    def push(self, result: Any) -> None:
        self._results.append(result)

    async def commit(self) -> None: ...
    async def execute(self, stmt: Any, params: dict[str, Any] | None = None) -> Any:
        self.calls.append((stmt, params or {}))
        if self._results:
            return self._results.pop(0)
        r = MagicMock()
        r.scalars.return_value.all.return_value = []
        return r


async def test_enqueue_event_passes_wildcard_candidates_to_sql():
    """The SQL bound param `wildcards` must carry the candidate
    list. Without that, `event_types && CAST(:wildcards AS text[])`
    would compare against an empty array and never match a wildcard
    subscription. Pin via the bound params."""
    from services.webhooks import enqueue_event

    session = _FakeSession()
    # Discovery query returns no subscriptions — we don't care about
    # what the query SELECTs; we want to pin the params.
    discovery = MagicMock()
    discovery.scalars.return_value.all.return_value = []
    session.push(discovery)

    await enqueue_event(
        session,  # type: ignore[arg-type]
        organization_id=ORG_ID,
        event_type="costpulse.estimate.approve",
        payload={},
    )

    sql, params = session.calls[0]
    assert "event_types && CAST(:wildcards AS text[])" in str(sql.text), (
        "enqueue_event SQL is missing the wildcard array overlap. "
        "Without it, a `costpulse.*` subscription would never receive "
        "any event."
    )
    assert params["event_type"] == "costpulse.estimate.approve"
    assert params["wildcards"] == ["costpulse.estimate.*", "costpulse.*"]
