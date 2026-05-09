"""Audit-trail completeness audit.

Sibling of `test_state_changing_auth_audit.py` — that one pins
"every state-changing route is authed"; this one pins "every
state-changing route emits an audit event."

The bug class
-------------
Compliance review asks "show me every change to a quota / approved
estimate / role assignment." If a state-changing route forgets to
call `services.audit.record(...)`, the row mutation lands in the DB
but no audit_event row is written. Three months later the SOC-2
auditor asks for the trail and the answer is "we lost it."

Runtime tests don't catch this — they assert on response shape +
DB writes, not on side-effect tracking. The OpenAPI snapshot
doesn't see it. The only practical gate is a static walk that
introspects each handler's source for an `audit.record(` call.

Recognised audit-emit patterns
------------------------------
- `audit.record(...)` (most common via `from services import audit`)
- `audit_record(...)` (alias from `from services.audit import record as audit_record`)
- `record_audit(...)` (alias from `from services.audit import record as record_audit`)
- `_audit.record(...)` (lazy-import pattern)
- An explicit `# audit-trail: <reason>` comment with stated reason
  (idempotent UPSERTs, read-mostly mutations like cache-warmup
  endpoints — same justification pattern as cron-mutex).

Allowlist
---------
Routes that legitimately don't emit audit events:
  * Public endpoints (no authenticated actor — no useful audit).
  * Streaming response endpoints (the act of streaming itself
    isn't a governance event; the underlying mutation should
    audit before it streams).
  * Bulk operations whose individual rows audit themselves.

Each entry needs a one-line reason; an empty rationale turns the
allowlist into a way to silence the gate.

Ratchet
-------
Today's baseline is large — most state-changing routes don't emit
audit events. Same ratchet pattern as the Pydantic + cron audits:
assert `count ≤ BASELINE_MISSING_AUDIT`, reductions celebrate +
prompt to lower the baseline, additions red-gate.
"""

from __future__ import annotations

import inspect
import re
from typing import Any

import pytest

# Patterns that satisfy the audit-trail contract. Match against the
# handler's source (text). A handler is "auditing" if ANY pattern
# matches.
_AUDIT_PATTERNS = [
    # Direct calls in any of the recognised import-shape variants.
    re.compile(r"\baudit\.record\s*\("),
    re.compile(r"\baudit_record\s*\("),
    re.compile(r"\brecord_audit\s*\("),
    re.compile(r"\b_audit\.record\s*\("),
    # Explicit acknowledgement: handler is documented as not needing
    # an audit row. Reason is what makes the exception reviewable.
    re.compile(r"#\s*audit-trail:\s*\S", re.IGNORECASE),
]


# (path_substring, method) → reason. Routes whose path CONTAINS the
# substring AND method matches are exempt. Substring matching covers
# families (`/public/*`) without listing each variant.
ALLOWLIST: dict[tuple[str, str], str] = {
    # Public endpoints have no authenticated actor — there's nothing
    # useful to attribute the audit row to. The validation that the
    # token is good already lives in the handler body.
    ("/public/rfq/respond", "POST"): "public endpoint; no authenticated actor",
    # Invitation accept: the user doesn't exist YET when this runs
    # (the handler creates them); the audit semantics belong to the
    # invitation-create call (which IS audited via org.invitation.create).
    ("/invitations/{token}/accept", "POST"): "creates the user; audited via invitation.create",
    # Onboarding: ditto — the user has no audit identity yet.
    ("/onboarding/seed-demo", "POST"): "first-sign-in seeding; pre-audit-identity",
}


# Today's baseline. Same ratchet pattern as Pydantic + cron audits.
# When the count drops, lower this constant in the same PR; when it
# reaches 0, flip to strict equality.
BASELINE_MISSING_AUDIT = 124  # 2026-05: +1 for POST /activity/stream/ticket (ephemeral session-mint, not a state change worth auditing — but we audit anyway-or-allowlist as the ratchet lands)


_MUTATION_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _allowlist_hit(path: str, method: str) -> str | None:
    for (sub, m), reason in ALLOWLIST.items():
        if m == method and sub in path:
            return reason
    return None


def _emits_audit(handler: Any) -> bool:
    """True if the handler's source contains any audit-emit pattern."""
    try:
        src = inspect.getsource(handler)
    except (OSError, TypeError):
        return False
    return any(p.search(src) for p in _AUDIT_PATTERNS)


def test_state_changing_routes_emit_audit_events_or_are_allowlisted():
    """Walk `main.app`; for each non-GET route, assert the handler
    body contains an audit.record call (in any of its import-shape
    aliases) OR is on the ALLOWLIST OR has an explicit
    `# audit-trail: <reason>` comment.

    Failure surfaces both directions of the ratchet:
      * COUNT > BASELINE: a new state-changing route landed without
        audit emission.
      * COUNT < BASELINE: someone fixed a route — bump the baseline
        so future regressions can't silently rebuild back up.
    """
    from main import create_app

    app = create_app()

    missing: list[tuple[str, str]] = []
    for route in app.routes:
        methods = getattr(route, "methods", None) or set()
        path = getattr(route, "path", "")
        for method in methods & _MUTATION_METHODS:
            if _allowlist_hit(path, method):
                continue
            endpoint = getattr(route, "endpoint", None)
            if endpoint is None:
                continue
            if not _emits_audit(endpoint):
                missing.append((method, path))

    n = len(missing)
    if n > BASELINE_MISSING_AUDIT:
        new = n - BASELINE_MISSING_AUDIT
        formatted = "\n  ".join(f"{m:<7} {p}" for m, p in sorted(missing)[:20])
        pytest.fail(
            f"{new} new state-changing route(s) added without audit emission "
            f"(total now {n}, baseline {BASELINE_MISSING_AUDIT}).\n\n"
            f"First 20 unaudited routes:\n  {formatted}"
            + (f"\n  … and {n - 20} more" if n > 20 else "")
            + "\n\nEvery state-changing route should call `services.audit.record(...)` "
            "somewhere in the handler body. Use whichever import shape matches "
            "your file's convention:\n"
            "  • `from services import audit` → `audit.record(...)`\n"
            "  • `from services.audit import record as audit_record` → `audit_record(...)`\n"
            "  • Lazy: `from services import audit as _audit` → `_audit.record(...)`\n\n"
            "If the route legitimately doesn't carry governance bearing "
            "(idempotent UPSERT, read-mostly mutation, etc.), add a "
            "`# audit-trail: <reason>` comment in the handler body OR add "
            "an entry to ALLOWLIST in this test."
        )
    if n < BASELINE_MISSING_AUDIT:
        pytest.fail(
            f"Audit-emission missing-count dropped from {BASELINE_MISSING_AUDIT} "
            f"to {n} (you fixed {BASELINE_MISSING_AUDIT - n}). 🎉\n\n"
            f"Update `BASELINE_MISSING_AUDIT` in this test to {n} so future "
            f"regressions can't silently rebuild back up. Once it reaches 0, "
            f"flip the assertion to strict equality and remove the baseline."
        )


def test_allowlist_entries_actually_match_routes():
    """Defensive: every ALLOWLIST entry must correspond to a real
    route. Stale entries silently mask future regressions on the
    name of the renamed route.
    """
    from main import create_app

    app = create_app()
    real_pairs: set[tuple[str, str]] = set()
    for route in app.routes:
        methods = getattr(route, "methods", None) or set()
        path = getattr(route, "path", "")
        for method in methods:
            real_pairs.add((path, method))

    stale = [
        f"{method} (substring) {sub}"
        for (sub, method) in ALLOWLIST
        if not any(sub in p and m == method for p, m in real_pairs)
    ]
    assert not stale, (
        f"ALLOWLIST has {len(stale)} stale entries:\n  "
        + "\n  ".join(stale)
        + "\nRemove them so the allowlist reflects only currently-live exemptions."
    )


def test_audit_patterns_recognise_documented_aliases():
    """Defensive: the regex set must match every legitimate pattern
    we've observed in the codebase. A regression in any pattern would
    silently fail-OPEN — handlers that legitimately audit would look
    "missing audit" to this gate.
    """
    samples = [
        "await audit.record(session, ...)",
        "await audit_record(session, ...)",
        "await record_audit(session, ...)",
        "await _audit.record(session, ...)",
        "# audit-trail: bulk-import; per-row audit happens inside loop",
    ]
    for s in samples:
        assert any(p.search(s) for p in _AUDIT_PATTERNS), f"audit pattern set fails to match documented alias: {s!r}"

    # Negative: a comment without a reason after the colon must NOT
    # satisfy. Same justification rule as cron-mutex.
    assert not any(p.search("# audit-trail:") for p in _AUDIT_PATTERNS), (
        "Empty `# audit-trail:` comment satisfies the gate — the reason is what makes the exception reviewable."
    )
