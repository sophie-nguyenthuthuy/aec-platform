"""Idempotency-key contract audit.

The bug class
-------------
A flaky network causes the client to retry a POST `/winwork/proposals`.
The first request actually succeeded — the response just didn't make
it back. Without idempotency, the retry creates a SECOND proposal.
The user sees two identical rows; data integrity bug.

The fix exists: `middleware/idempotency_route.py::IdempotentRoute`.
A router that uses `route_class=IdempotentRoute` transparently
handles `Idempotency-Key` headers — duplicate keys replay the cached
response instead of re-running the handler. Today some routers
adopt it; others don't.

What this audit checks
----------------------
For every POST endpoint that creates a resource — heuristics: name
starts with `create_`/`generate_`, OR returns 201 Created, OR path
ends in a noun like `/proposals` / `/tasks` / `/defects` (a
collection POST creating a new item) — assert the route's class is
`IdempotentRoute` (or a subclass).

Allowlist for legitimately non-idempotent POSTs:
  * Read-only POSTs (`/codeguard/query`, `/drawbridge/query`) —
    these compute an answer, they don't create state.
  * Action POSTs that operate on existing resources
    (`/proposals/{id}/send`, `/cos/{id}/analyze`).
  * Bulk operations whose internal idempotency is row-level
    (`/tasks/bulk`).

Each allowlist entry needs a stated reason; an empty rationale
turns the audit into a way to silence the gate.

Same ratchet pattern as prior audits.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

# Path patterns that look like "create a resource" POSTs. Heuristic:
# the path's final segment is a plural noun (no `{id}` placeholder),
# meaning the POST creates a new item in the collection.
_CREATE_PATH_RE = re.compile(
    r"/(proposals|tasks|change-orders|meeting-notes|client-reports|"
    r"watches|api-keys|projects|estimates|suppliers|rfq|price-alerts|"
    r"visits|reports|packages|closeout-items|as-builts|warranties|"
    r"defects|documents|document-sets|rfis|schedules|activities|"
    r"dependencies|submittals|revisions|logs|observations|cos|"
    r"line-items|approvals|sources|lists|items|orgs|invitations|"
    r"members)$"
)


# POSTs whose path matches `_CREATE_PATH_RE` but that legitimately
# don't need idempotency. Each entry needs a stated reason.
ALLOWLIST: dict[tuple[str, str], str] = {
    # No entries today. Add lazily as legitimate exceptions surface
    # — the dominant case is "creation POSTs need idempotency."
}


# Today's baseline. Most creation POSTs don't yet adopt
# IdempotentRoute. Same ratchet as Pydantic + cron audits.
BASELINE_NON_IDEMPOTENT_CREATES = 33  # 2026-05: 🎉 ratcheted down 34→33 — one creation POST adopted IdempotentRoute


def _is_idempotent_route(route: Any) -> bool:
    """True if the route's class is `IdempotentRoute` (or a subclass)."""
    try:
        from middleware.idempotency_route import IdempotentRoute
    except ImportError:
        return False
    return isinstance(route, IdempotentRoute)


def _looks_like_create(path: str, method: str) -> bool:
    if method != "POST":
        return False
    return bool(_CREATE_PATH_RE.search(path))


def _allowlist_hit(path: str, method: str) -> str | None:
    return ALLOWLIST.get((path, method))


def test_every_creation_post_uses_idempotent_route():
    """Walk `main.app`; for each POST whose path matches a
    creation-collection pattern, assert the route's class is
    `IdempotentRoute`. Failures surface both ratchet directions.
    """
    from main import create_app

    app = create_app()

    non_idempotent: list[tuple[str, str]] = []
    for route in app.routes:
        methods = getattr(route, "methods", None) or set()
        path = getattr(route, "path", "")
        for method in methods:
            if not _looks_like_create(path, method):
                continue
            if _allowlist_hit(path, method):
                continue
            if not _is_idempotent_route(route):
                non_idempotent.append((method, path))

    n = len(non_idempotent)
    if n > BASELINE_NON_IDEMPOTENT_CREATES:
        new = n - BASELINE_NON_IDEMPOTENT_CREATES
        formatted = "\n  ".join(f"{m:<7} {p}" for m, p in sorted(non_idempotent)[:20])
        pytest.fail(
            f"{new} new creation POST(s) without IdempotentRoute "
            f"(total now {n}, baseline {BASELINE_NON_IDEMPOTENT_CREATES}).\n\n"
            f"First 20:\n  {formatted}"
            + (f"\n  … and {n - 20} more" if n > 20 else "")
            + "\n\nAdopt IdempotentRoute on the router declaration:\n\n"
            "    from middleware.idempotency_route import IdempotentRoute\n"
            "    router = APIRouter(prefix='...', route_class=IdempotentRoute)\n\n"
            "POST/PATCH/DELETE on that router will then transparently "
            "handle the `Idempotency-Key` header — duplicate keys replay "
            "the cached response without re-running the handler.\n\n"
            "If a route legitimately doesn't need idempotency (read-only "
            "compute, bulk op with row-level idempotency), add to "
            "ALLOWLIST with a stated reason."
        )
    if n < BASELINE_NON_IDEMPOTENT_CREATES:
        pytest.fail(
            f"Non-idempotent-creates count dropped from "
            f"{BASELINE_NON_IDEMPOTENT_CREATES} to {n}. 🎉 Update "
            f"`BASELINE_NON_IDEMPOTENT_CREATES` to {n} so future "
            f"regressions can't rebuild back up."
        )


def test_create_pattern_matches_at_least_some_routes():
    """Defensive: the heuristic regex should match at least 5 real
    routes today. If it matches none, the regex is broken (typo,
    overly-strict pattern) and the audit has no teeth.
    """
    from main import create_app

    app = create_app()
    matches: list[str] = []
    for route in app.routes:
        methods = getattr(route, "methods", None) or set()
        path = getattr(route, "path", "")
        if "POST" in methods and _CREATE_PATH_RE.search(path):
            matches.append(path)
    assert len(matches) >= 5, (
        f"_CREATE_PATH_RE matched only {len(matches)} routes "
        f"({matches!r}). The regex is probably stale; update it to "
        f"reflect the current router shape."
    )


def test_idempotent_route_class_is_importable():
    """The audit depends on importing `IdempotentRoute`. If the
    middleware module gets renamed/moved, the audit silently
    fail-OPENS — every route reports as 'not idempotent' but the
    type-check would just return False because the import failed.
    Pin importability as a separate sanity check.
    """
    from middleware.idempotency_route import IdempotentRoute

    assert IdempotentRoute is not None
    assert hasattr(IdempotentRoute, "get_route_handler")  # subclass of APIRoute
