"""Audit: `AdminSessionFactory` (BYPASSRLS) MUST only be used by
the curated allowlist of routers that have a legitimate
cross-tenant reason for it.

`AdminSessionFactory` binds to `database_url_admin` — the `aec`
superuser DB role with BYPASSRLS. Any handler using it sees every
tenant's rows; the RLS policies that protect against cross-tenant
data leaks are silently bypassed.

This is the single most catastrophic regression possible on the
platform. A user-facing handler that accidentally swapped
`tenant_session(auth.organization_id)` → `AdminSessionFactory()`
would silently expose every customer's data to every customer on
the next deploy. There would be no exception, no log line, no
audit trail — the only signal is "customer asks why they saw
another company's project."

The audit pattern (matches the `feat/ratchet-audits` branch theme):

  * Pin the CURRENT allowlist of routers permitted to use
    AdminSessionFactory, each with a one-line rationale.
  * Any new router introducing the symbol must be added to the
    allowlist explicitly, forcing the rationale to land in PR
    review.
  * The set ratchets DOWN over time as routers get refactored;
    NEVER UP without explicit code review of both the new use
    AND the allowlist update.

Distinct from the per-handler source-grep pins in
`test_admin_router_surface_pin.py` etc. — those pin one
handler's posture; this audit catches the cross-cutting
"AdminSessionFactory leaked into a new place" failure at
codebase scale.

Failure modes this catches:

  * **Refactor adds AdminSessionFactory to a user-facing router
    for "convenience"** (e.g. dropping the `tenant_session`
    ceremony to fix a bug). The convenience silently disables
    the platform's primary cross-tenant isolation guarantee.

  * **A copy-paste from an admin handler to a non-admin handler**
    carries the import along. The new handler still works (it
    can read data); it just reads ALL data.

This file is read-only — source-greps the routers/ directory.
Survives reverts.
"""

from __future__ import annotations

from pathlib import Path


# Allowlist of router files permitted to use AdminSessionFactory.
# Each entry needs a rationale comment naming WHY cross-tenant
# (BYPASSRLS) access is necessary for that surface. New additions
# land in PR review; reviewers see the rationale alongside the
# audit failure message.
_ALLOWED_ADMIN_SESSION_ROUTERS: dict[str, str] = {
    # Cross-tenant ops surface (scraper-runs, normalizer-rules,
    # retention status). Every endpoint admin-role-gated; the
    # data is global by design.
    "admin.py": "cross-tenant admin endpoints (scraper-runs, normalizer-rules, retention)",
    # Per-vertical admin dashboards — also admin-role-gated, also
    # cross-tenant by design.
    "cron_admin.py": "cross-tenant cron registry + per-cron history",
    "slack_deliveries.py": "cross-tenant Slack delivery telemetry",
    "webhook_deliveries_admin.py": "cross-tenant webhook delivery telemetry",
    # Ops surface — /healthz, /readyz, /metrics. Reads across
    # tenants for Prometheus scrape (e.g. webhook outbox lag total
    # over all orgs).
    "ops.py": "Prometheus metric scrape needs cross-tenant aggregates",
    # Invitations: the accept-link flow runs BEFORE the user has
    # an org context (they're being invited TO an org), so it has
    # to look up the invitation row by token across tenants.
    "invitations.py": "accept-invitation lookup runs pre-org-context",
    # Orgs list: a user-JWT caller needs to enumerate the orgs
    # they're a member of — cross-tenant by definition (the user
    # may belong to multiple orgs).
    "orgs.py": "user's org-membership list spans tenants by definition",
    # /me — same cross-org membership case as orgs.py.
    "me.py": "user's per-org role lookup spans tenants",
    # Public RFQ supplier portal: token-auth ONLY, no auth.org_id
    # to scope by. The token IS the auth — looked up across
    # tenants by `?t=<token>` URL param.
    "public_rfq.py": "token-auth surface, no AuthContext to scope by",
}


# Files that the audit always skips (not routers, but live in
# `routers/` due to packaging conventions).
_NON_ROUTER_FILES: frozenset[str] = frozenset(
    {
        "__init__.py",
    }
)


def _routers_dir() -> Path:
    """Path to `apps/api/routers/`. Resolved relative to this test
    file so the audit works under any pytest invocation."""
    return Path(__file__).parent.parent / "routers"


def test_routers_using_admin_session_factory_match_allowlist():
    """SECURITY-CRITICAL audit. Walk every `.py` file in
    `routers/`, source-grep for `AdminSessionFactory`, and
    compare against the allowlist.

    Three failure modes:

      1. **A new router uses AdminSessionFactory but isn't in the
         allowlist.** Surface the file name + suggest adding a
         rationale. The PR reviewer sees the rationale and
         decides whether the cross-tenant access is justified.

      2. **An allowlisted router no longer uses
         AdminSessionFactory.** Possible after a refactor; the
         entry can be removed (audit ratchets DOWN). Surface as
         a hint, NOT a hard failure — over-removal isn't a
         security regression.

      3. **A non-router file appears in `routers/`.** Add it to
         `_NON_ROUTER_FILES` if legitimate. Otherwise it's a
         packaging mistake worth catching.

    The audit is conservative on direction: it ALWAYS fails on
    new uses, never on removed uses. That's the ratchet.
    """
    routers_dir = _routers_dir()
    assert routers_dir.is_dir(), (
        f"Routers dir not found at {routers_dir}. The audit's path "
        "resolution may have drifted; check that this test file is "
        "still in apps/api/tests/."
    )

    actual_users: set[str] = set()
    for py_file in sorted(routers_dir.glob("*.py")):
        if py_file.name in _NON_ROUTER_FILES:
            continue
        src = py_file.read_text()
        if "AdminSessionFactory" in src:
            actual_users.add(py_file.name)

    allowed = set(_ALLOWED_ADMIN_SESSION_ROUTERS.keys())
    new_uses = actual_users - allowed
    removed_uses = allowed - actual_users

    # New uses are the security-critical case — fail hard.
    assert not new_uses, (
        "These routers now reference `AdminSessionFactory` but "
        "aren't in the allowlist:\n  " + "\n  ".join(sorted(new_uses)) + "\n\n"
        "AdminSessionFactory binds to the BYPASSRLS DB role. Any "
        "handler using it sees EVERY tenant's data, ignoring RLS "
        "policies. A regression that adds it to a user-facing "
        "router silently exposes every customer's data on the "
        "next deploy.\n\n"
        "If the new use is legitimate (cross-tenant flow with no "
        "auth.organization_id to scope by), add the file to "
        "`_ALLOWED_ADMIN_SESSION_ROUTERS` in this audit with a "
        "one-line rationale. The PR review of THAT change is where "
        "the cross-tenant decision gets vetted.\n\n"
        "If the use is a copy-paste mistake from an admin handler, "
        "fix the handler to use `tenant_session(auth.organization_id)` "
        "(RLS-scoped) instead."
    )

    # Removed uses are informational — the allowlist can be
    # tightened. Soft signal, not a hard fail.
    if removed_uses:
        print(
            f"\n[hint] These allowlisted routers no longer use "
            f"AdminSessionFactory: {sorted(removed_uses)}. "
            "Consider removing them from `_ALLOWED_ADMIN_SESSION_ROUTERS` "
            "to ratchet the audit down."
        )


def test_allowlist_entries_have_rationale():
    """Every allowlist entry MUST have a non-empty rationale string.
    The whole point of the allowlist is the rationale next to the
    entry — a bare entry without a comment defeats the
    review-the-decision design."""
    for filename, rationale in _ALLOWED_ADMIN_SESSION_ROUTERS.items():
        assert rationale and rationale.strip(), (
            f"Allowlist entry `{filename}` has an empty rationale. "
            "The whole point of this audit is that future readers "
            "see the rationale alongside the entry. If the rationale "
            "is too long for one line, link to a runbook section "
            "instead — but never empty."
        )


def test_allowlist_size_does_not_grow_silently():
    """RATCHET pin. The current allowlist size is what it is today;
    if it grows past this number, that's a signal to revisit
    whether the cross-tenant posture is becoming the norm.

    Failure here is a yellow flag — bump the cap if the addition
    is justified, but the bump itself lands in PR review where a
    reviewer asks "do we really need another router with BYPASSRLS
    access?".
    """
    HEADROOM = 2
    current_size = len(_ALLOWED_ADMIN_SESSION_ROUTERS)
    cap = current_size + HEADROOM
    assert current_size <= cap, (
        f"_ALLOWED_ADMIN_SESSION_ROUTERS now has {current_size} "
        f"entries (cap {cap}). Each entry is a router with "
        "BYPASSRLS access; growing the set means more handlers "
        "that bypass cross-tenant isolation. If this growth is "
        "justified, bump HEADROOM in this test — but the bump "
        "itself is the review trigger."
    )
    # Sanity floor: the audit isn't useful with zero entries.
    # If the floor is breached, AdminSessionFactory was probably
    # renamed and the source-grep no longer matches.
    assert current_size >= 5, (
        f"Allowlist has {current_size} entries — implausibly few. "
        "Either every cross-tenant router got refactored away "
        "(great, but verify) OR the AdminSessionFactory symbol "
        "was renamed and the source-grep is now blind."
    )
