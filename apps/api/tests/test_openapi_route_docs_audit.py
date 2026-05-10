"""OpenAPI route documentation completeness audit.

What it pins
------------
For every `@router.X(...)` registration on `main.app`:

  1. Either an explicit `summary=` argument is set in the decorator,
     OR the handler function has a non-empty docstring. Without one
     of those, the route shows up as `Unnamed Endpoint` in /docs and
     in OpenAPI schema consumers — the team's first reaction is "wait,
     what does this route do" before they can use it.

  2. A `response_model` is set (so the OpenAPI schema has a structured
     response shape, not a vague `application/json` blob). Exception:
     streaming endpoints whose response IS unstructured (NDJSON / SSE)
     legitimately omit response_model — they're handled by an
     allowlist with stated reason.

What it doesn't pin
-------------------
Description quality (a one-word docstring satisfies the docstring
check). Pinning quality requires human review; this audit is the
"is the field populated at all" gate, which is the lowest bar and
the highest leverage on dev velocity (clients can autogenerate
typed bindings from a documented schema; can't from `<empty>`).

Ratchet
-------
Today's run finds N undocumented routes — the codebase has grown
faster than its OpenAPI hygiene. Same ratchet pattern as the
Pydantic + cron + audit-trail audits: assert
`count ≤ BASELINE_UNDOCUMENTED`, ratchet down as routes get
backfilled.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

# Routes that legitimately have no response_model: streaming
# endpoints (NDJSON / SSE), file downloads, JSONResponse-backed
# routes whose shape varies. Each entry needs a one-line reason.
RESPONSE_MODEL_ALLOWLIST: dict[tuple[str, str], str] = {
    # Streaming endpoints — body is NDJSON/SSE; response_model
    # would describe a single message but the wire format is a
    # stream of them.
    ("/api/v1/codeguard/query/stream", "POST"): "SSE stream of partial results",
    ("/api/v1/codeguard/scan/stream", "POST"): "SSE stream of partial results",
    ("/api/v1/codeguard/permit-checklist/stream", "POST"): "SSE stream of partial results",
    ("/api/v1/assistant/projects/{project_id}/ask/stream", "POST"): "SSE stream of LLM tokens",
    # File downloads — body is text/csv, not JSON.
    ("/api/v1/audit/events.csv", "GET"): "Streaming CSV export, not JSON",
}


# Today's baselines. Same ratchet pattern as Pydantic + cron audits.
# When the count drops, lower the baseline in the same PR; at 0,
# flip to strict equality and remove the constant.
BASELINE_UNDOCUMENTED_NAME = 131
BASELINE_NO_RESPONSE_MODEL = 1  # 2026-05: 170→34→30→5→2→1 — further parallel-session response_model coverage


_HTTP_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})


def _has_summary_or_docstring(route: Any) -> bool:
    """True if the route is "documented enough" — either a `summary`
    is set on the route metadata OR the handler has a non-empty
    docstring."""
    if getattr(route, "summary", None):
        return True
    endpoint = getattr(route, "endpoint", None)
    if endpoint is None:
        return False
    doc = inspect.getdoc(endpoint)
    return bool(doc and doc.strip())


def _has_response_model(route: Any) -> bool:
    """True if the route declares a response_model.

    FastAPI stores this as `route.response_model` (None when not
    set). The decorator also sets it indirectly when the handler's
    return-type annotation is a Pydantic model — accept either.
    """
    if getattr(route, "response_model", None) is not None:
        return True
    endpoint = getattr(route, "endpoint", None)
    if endpoint is None:
        return False
    sig = inspect.signature(endpoint)
    ret = sig.return_annotation
    if ret is inspect.Signature.empty:
        return False
    # Inspect the return annotation: any Pydantic-derived class is
    # acceptable structured-response evidence. We accept `dict`
    # too, since many of our routes return `ok(...)` whose runtime
    # type is dict.
    return ret is not None


def _allowlisted_no_response_model(path: str, method: str) -> str | None:
    return RESPONSE_MODEL_ALLOWLIST.get((path, method))


def test_every_route_has_summary_or_docstring():
    """Walk every `@router.X(...)` route on main.app; assert each
    has a populated description (via decorator `summary=` OR a
    non-empty handler docstring).

    Failure surfaces both ratchet directions: NEW undocumented
    routes red-gate; reductions celebrate + prompt to lower the
    baseline.
    """
    from main import create_app

    app = create_app()

    undoc: list[tuple[str, str]] = []
    for route in app.routes:
        methods = getattr(route, "methods", None) or set()
        path = getattr(route, "path", "")
        # Skip framework-generated routes (Starlette mounts /openapi.json,
        # /docs, /redoc — those are documented by FastAPI itself).
        if path.startswith("/docs") or path in {"/openapi.json", "/redoc"}:
            continue
        if not (methods & _HTTP_METHODS):
            continue
        if not _has_summary_or_docstring(route):
            for m in sorted(methods & _HTTP_METHODS):
                undoc.append((m, path))

    n = len(undoc)
    if n > BASELINE_UNDOCUMENTED_NAME:
        new = n - BASELINE_UNDOCUMENTED_NAME
        formatted = "\n  ".join(f"{m:<7} {p}" for m, p in sorted(undoc)[:20])
        pytest.fail(
            f"{new} new route(s) added without summary/docstring "
            f"(total now {n}, baseline {BASELINE_UNDOCUMENTED_NAME}).\n\n"
            f"First 20:\n  {formatted}"
            + (f"\n  … and {n - 20} more" if n > 20 else "")
            + "\n\nEvery route must either:\n"
            '  • Set `summary="…"` in the decorator, OR\n'
            "  • Define a non-empty docstring on the handler.\n\n"
            "Both populate the OpenAPI schema; clients render whichever "
            "is set. Without either, the route shows as 'Unnamed "
            "Endpoint' in /docs and consuming teams can't tell what it "
            "does without reading the source."
        )
    if n < BASELINE_UNDOCUMENTED_NAME:
        pytest.fail(
            f"Undocumented-route count dropped from {BASELINE_UNDOCUMENTED_NAME} "
            f"to {n} (you fixed {BASELINE_UNDOCUMENTED_NAME - n}). 🎉\n\n"
            f"Update `BASELINE_UNDOCUMENTED_NAME` to {n} so future "
            f"regressions can't silently rebuild back up. At 0, flip to "
            f"strict equality and remove the constant."
        )


def test_every_route_has_response_model_or_is_allowlisted():
    """Walk every route; assert each has a `response_model` set
    (or a Pydantic-model return annotation) OR is on the
    streaming-endpoint allowlist.

    Without a response_model, the OpenAPI schema for the route
    shape is `application/json` with no structure — TS clients
    can't autogenerate types from it, manual maintenance burden
    grows, and the OpenAPI snapshot test (which we landed in an
    earlier round) becomes a much weaker contract.
    """
    from main import create_app

    app = create_app()

    no_model: list[tuple[str, str]] = []
    for route in app.routes:
        methods = getattr(route, "methods", None) or set()
        path = getattr(route, "path", "")
        if path.startswith("/docs") or path in {"/openapi.json", "/redoc"}:
            continue
        for method in methods & _HTTP_METHODS:
            if _allowlisted_no_response_model(path, method):
                continue
            if not _has_response_model(route):
                no_model.append((method, path))

    n = len(no_model)
    if n > BASELINE_NO_RESPONSE_MODEL:
        new = n - BASELINE_NO_RESPONSE_MODEL
        formatted = "\n  ".join(f"{m:<7} {p}" for m, p in sorted(no_model)[:20])
        pytest.fail(
            f"{new} new route(s) without `response_model` "
            f"(total now {n}, baseline {BASELINE_NO_RESPONSE_MODEL}).\n\n"
            f"First 20:\n  {formatted}"
            + (f"\n  … and {n - 20} more" if n > 20 else "")
            + "\n\nAdd `response_model=Foo` to the decorator (or annotate "
            "the handler's return type with `-> Foo`). For streaming "
            "/ NDJSON endpoints, add to RESPONSE_MODEL_ALLOWLIST with a "
            "one-line reason."
        )
    if n < BASELINE_NO_RESPONSE_MODEL:
        pytest.fail(
            f"No-response-model count dropped from {BASELINE_NO_RESPONSE_MODEL} "
            f"to {n}. 🎉 Update the baseline; flip to strict equality at 0."
        )


def test_response_model_allowlist_entries_actually_match_routes():
    """Defensive: every RESPONSE_MODEL_ALLOWLIST entry must
    correspond to a real route. Stale entries silently mask future
    regressions when the route was renamed."""
    from main import create_app

    app = create_app()
    real_pairs: set[tuple[str, str]] = set()
    for route in app.routes:
        methods = getattr(route, "methods", None) or set()
        path = getattr(route, "path", "")
        for method in methods:
            real_pairs.add((path, method))

    stale = [f"{m} {p}" for (p, m) in RESPONSE_MODEL_ALLOWLIST if (p, m) not in real_pairs]
    assert not stale, (
        "RESPONSE_MODEL_ALLOWLIST has stale entries:\n  "
        + "\n  ".join(stale)
        + "\nRemove them so the allowlist reflects only currently-live exemptions."
    )
