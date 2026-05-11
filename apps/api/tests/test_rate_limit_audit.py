"""Per-tenant rate-limit audit.

Sibling of `test_state_changing_auth_audit.py` — that one pins
"every state-changing route is authed"; this one pins "every
expensive-backend endpoint has a rate limit wired."

The bug class
-------------
A new endpoint hits an LLM (Anthropic / OpenAI) or a paid third-
party API. The author forgets to wire `Depends(rate_limit(...))`.
One noisy tenant burns through the whole platform's API budget in
a few minutes — by the time alerts fire, the bill is real.

Or: a file-upload endpoint without a rate limit becomes the path of
least resistance for a client to push GB of garbage through.

What this audit checks
----------------------
For every route whose path matches a curated set of "expensive"
patterns (LLM-calling routes, file uploads, bulk imports), assert
the FastAPI dependency tree contains a recognised rate-limit dep.

Recognised deps:
  * `_dep_ip` / `_dep_keyed` — the closures `core.rate_limit.rate_limit(...)`
    returns.
  * `require_api_key_rate_limit` — the API-key sibling primitive.

Allowlist
---------
Routes that legitimately don't need a rate limit on the LLM-cost
path (e.g. internal admin endpoints behind RBAC + IP allowlisting).
Each entry needs a stated reason; an empty rationale turns the
allowlist into a way to silence the gate.

Same ratchet pattern as the auth + audit-trail audits.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

# Path patterns that warrant rate limiting. Each is a `re.compile`
# pattern matched against the route path.
EXPENSIVE_PATH_PATTERNS = [
    # LLM-calling routes — every Anthropic/OpenAI hit costs us money.
    re.compile(r"/codeguard/(query|scan|permit-checklist)"),
    re.compile(r"/winwork/proposals/generate"),
    re.compile(r"/winwork/fee-estimate"),
    re.compile(r"/pulse/meeting-notes/structure"),
    re.compile(r"/pulse/client-reports/generate"),
    re.compile(r"/pulse/change-orders/[^/]+/analyze"),
    re.compile(r"/drawbridge/(query|extract|conflict-scan)"),
    re.compile(r"/drawbridge/rfis/generate"),
    re.compile(r"/drawbridge/rfis/[^/]+/answer"),
    re.compile(r"/dailylog/logs/[^/]+/extract"),
    re.compile(r"/changeorder/(extract|cos/[^/]+/analyze)"),
    re.compile(r"/handover/om-manuals/generate"),
    re.compile(r"/handover/warranties/extract"),
    re.compile(r"/siteeye/reports/generate"),
    re.compile(r"/submittals/rfis/[^/]+/(embed|draft)"),
    re.compile(r"/assistant/projects/[^/]+/ask"),
    re.compile(r"/costpulse/estimate/from-(brief|drawings)"),
    re.compile(r"/bidradar/(scrape|score)"),
    re.compile(r"/schedule/schedules/[^/]+/risk-assessment"),
    # File uploads — bandwidth + storage abuse vector.
    re.compile(r"/drawbridge/documents/upload"),
    re.compile(r"/siteeye/photos/upload"),
    re.compile(r"/files$"),
    # Bulk imports — heavy DB writes.
    re.compile(r"/import/[^/]+/preview"),
    re.compile(r"/import/jobs/[^/]+/commit"),
]


# Recognised rate-limit dep names. Match against the function
# `__name__` in the dependency tree.
_RATE_LIMIT_DEP_NAMES = frozenset(
    [
        "_dep_ip",  # rate_limit(...) factory output, IP-keyed
        "_dep_keyed",  # rate_limit(...) factory output, custom-keyed
        "require_api_key_rate_limit",  # API-key sibling primitive
        "check_rate_limit",  # used directly in some manual paths
    ]
)


# Routes that legitimately don't need a rate limit. Each needs a
# stated reason; otherwise the entry just silences the gate.
ALLOWLIST: dict[tuple[str, str], str] = {
    # Bidradar scrape is admin-only (cron-driven in prod, manual-trigger
    # in admin UI); the cron itself is on a fixed schedule, not a
    # user-controllable knob.
    ("/api/v1/bidradar/scrape", "POST"): "admin-only; cron-driven trigger, not per-user",
    ("/api/v1/bidradar/score", "POST"): "admin-only; cron-driven trigger, not per-user",
}


# Today's baseline — most expensive endpoints don't yet have rate
# limits. Same ratchet as Pydantic + cron audits.
BASELINE_UNGUARDED_EXPENSIVE = 34


_MUTATION_METHODS = frozenset({"POST", "PUT", "PATCH"})


def _walk_dep_names(dep: Any, seen: set[int] | None = None):
    """Yield every dependency callable's __name__ in the tree.

    Same shape as the auth-audit walker — recurse through both
    `dep.dependencies` and the closures Depends-marker arguments
    capture.
    """
    if seen is None:
        seen = set()
    if id(dep) in seen:
        return
    seen.add(id(dep))

    call = getattr(dep, "call", None)
    if call is not None:
        name = getattr(call, "__name__", None)
        if name:
            yield name
        closure = getattr(call, "__closure__", None) or ()
        for cell in closure:
            try:
                v = cell.cell_contents
            except ValueError:
                continue
            inner_name = getattr(v, "__name__", None)
            if inner_name:
                yield inner_name
            inner_dep = getattr(v, "dependency", None)
            if inner_dep is not None:
                inner_dep_name = getattr(inner_dep, "__name__", None)
                if inner_dep_name:
                    yield inner_dep_name

    for sub in getattr(dep, "dependencies", ()):
        yield from _walk_dep_names(sub, seen)


def _has_rate_limit(dep: Any) -> bool:
    return any(name in _RATE_LIMIT_DEP_NAMES for name in _walk_dep_names(dep))


def _is_expensive(path: str) -> bool:
    return any(p.search(path) for p in EXPENSIVE_PATH_PATTERNS)


def _allowlist_hit(path: str, method: str) -> str | None:
    return ALLOWLIST.get((path, method))


def test_every_expensive_route_has_a_rate_limit():
    """Walk `main.app`; for each route whose path matches an
    expensive pattern AND whose method is state-changing, assert
    a recognised rate-limit dep is in the dependency tree.
    """
    from main import create_app

    app = create_app()

    unguarded: list[tuple[str, str]] = []
    for route in app.routes:
        methods = getattr(route, "methods", None) or set()
        path = getattr(route, "path", "")
        if not _is_expensive(path):
            continue
        for method in methods & _MUTATION_METHODS:
            if _allowlist_hit(path, method):
                continue
            dep = getattr(route, "dependant", None)
            if dep is None:
                continue
            if not _has_rate_limit(dep):
                unguarded.append((method, path))

    n = len(unguarded)
    if n > BASELINE_UNGUARDED_EXPENSIVE:
        new = n - BASELINE_UNGUARDED_EXPENSIVE
        formatted = "\n  ".join(f"{m:<7} {p}" for m, p in sorted(unguarded)[:20])
        pytest.fail(
            f"{new} new expensive route(s) without a rate limit "
            f"(total now {n}, baseline {BASELINE_UNGUARDED_EXPENSIVE}).\n\n"
            f"First 20:\n  {formatted}"
            + (f"\n  … and {n - 20} more" if n > 20 else "")
            + "\n\nWire `Depends(rate_limit(prefix='...', limit=N, "
            "window_sec=W))` into the handler. Per-tenant keying via "
            "`key_dep=Depends(...)` resolving to the org_id is the "
            "right default — IP-keyed (the no-keydep fallback) is too "
            "coarse for multi-tenant fairness.\n\n"
            "If a route legitimately doesn't need a rate limit "
            "(admin-only with separate IP-allowlist defence, internal "
            "trigger), add it to ALLOWLIST with a stated reason."
        )
    if n < BASELINE_UNGUARDED_EXPENSIVE:
        pytest.fail(
            f"Unguarded-expensive count dropped from "
            f"{BASELINE_UNGUARDED_EXPENSIVE} to {n}. 🎉 Update "
            f"`BASELINE_UNGUARDED_EXPENSIVE` to {n} so future "
            f"regressions can't silently rebuild back up."
        )


def test_allowlist_entries_actually_match_routes():
    """Defensive: every ALLOWLIST entry must correspond to a real
    route. Stale entries silently mask future regressions when the
    route was renamed.
    """
    from main import create_app

    app = create_app()
    real_pairs = {(getattr(r, "path", ""), m) for r in app.routes for m in (getattr(r, "methods", None) or set())}
    stale = [f"{m} {p}" for (p, m) in ALLOWLIST if (p, m) not in real_pairs]
    assert not stale, (
        "ALLOWLIST has stale entries:\n  "
        + "\n  ".join(stale)
        + "\nRemove them so the allowlist reflects only currently-live exemptions."
    )


def test_expensive_path_patterns_match_at_least_one_route_each():
    """Defensive: every EXPENSIVE_PATH_PATTERNS regex must match
    at least one current route. A regex that matches nothing is
    either a typo OR a stale entry from a renamed route — either
    way, the audit has a hole.

    Stale patterns silently let new endpoints under the same
    semantic family slip through the audit.
    """
    from main import create_app

    app = create_app()
    paths = [getattr(r, "path", "") for r in app.routes]

    stale_patterns: list[str] = []
    for pat in EXPENSIVE_PATH_PATTERNS:
        if not any(pat.search(p) for p in paths):
            stale_patterns.append(pat.pattern)
    assert not stale_patterns, (
        f"{len(stale_patterns)} EXPENSIVE_PATH_PATTERNS regex(es) match "
        f"no current route:\n  "
        + "\n  ".join(stale_patterns)
        + "\n\nEither the route was renamed (update the regex) or it was "
        "removed (delete the pattern)."
    )
