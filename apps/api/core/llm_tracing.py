"""Sentry-aware tracing for LLM calls.

When Sentry is configured (`SENTRY_DSN` set), wrap each LLM invocation
in a Sentry span so slow / errored calls become traceable in the
dashboard. When Sentry isn't installed or DSN is empty, the wrapper is
a no-op — same surface, zero overhead.

Pipelines that already have their own structured-log telemetry
(`apps/ml/pipelines/codeguard.py::_record_llm_call`) can compose this
on top: the local handler captures token counts for cost accounting,
the Sentry span captures latency + breadcrumbs for incident debugging.
The two surfaces don't overlap.

Usage:

    async with llm_span("winwork.scope_generator", model="claude-sonnet-4-6"):
        raw = await chain.ainvoke({...})

A failed call propagates the exception (Sentry catches it via the
`except`-block); a slow but successful call shows up as a long span.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator
from typing import Any

logger = logging.getLogger(__name__)


@contextlib.asynccontextmanager
async def llm_span(
    operation: str,
    *,
    model: str,
    extra: dict[str, Any] | None = None,
) -> AsyncIterator[Any]:
    """Open a Sentry span for an LLM call.

    `operation` is a stable symbolic name like `"winwork.scope_generator"`
    — used as the Sentry `op` field, so dashboards can filter by call site.
    `model` is the LLM model identifier, attached as a span tag.
    `extra` is a dict of additional tag → value pairs (e.g. project_id,
    org_id) — keep these low-cardinality to avoid blowing up Sentry's
    tag store.

    Yields the underlying span object on success (a `sentry_sdk.tracing.Span`
    when Sentry is on, otherwise a do-nothing placeholder).
    """
    try:
        import sentry_sdk
    except ImportError:
        # SDK not installed — no-op context. Yields a placeholder so
        # callers that touch the span value still work.
        yield _NoSpan()
        return

    if sentry_sdk.Hub.current.client is None:
        # SDK installed but never `sentry_sdk.init`-ed (DSN was empty).
        # Same no-op behavior as above.
        yield _NoSpan()
        return

    with sentry_sdk.start_span(op="ai.llm", description=operation) as span:
        span.set_tag("llm.model", model)
        span.set_tag("llm.operation", operation)
        for k, v in (extra or {}).items():
            span.set_tag(f"llm.{k}", str(v))
        try:
            yield span
        except Exception as exc:
            span.set_status("internal_error")
            span.set_data("error", str(exc))
            raise


class _NoSpan:
    """Stand-in for a Sentry span when the SDK isn't initialized.

    Exposes the same `set_tag` / `set_data` / `set_status` surface
    callers use, so code that opportunistically attaches metadata to
    the yielded span doesn't need a `if span:` guard at every call site.
    """

    def set_tag(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def set_data(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def set_status(self, *_args: Any, **_kwargs: Any) -> None:
        return None
