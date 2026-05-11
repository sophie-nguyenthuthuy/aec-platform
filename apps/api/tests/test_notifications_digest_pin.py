"""Pin the `services.notifications` daily-digest pipeline.

This module is the per-user activity-digest sender — fans out one
email per (user, org) pair daily at 07:00 ICT. Failure modes a
regression here can produce, with their visibility:

  * **Empty-digest spam.** Returns None when the user has no events
    so the cron skips them. A regression that returned a non-None
    payload on empty rows would email every quiet day's user — the
    "we sent you a digest with no content" complaint that erodes
    open rates and trains users to ignore us.

  * **Cross-tenant leak.** The digest SQL filters on
    `organization_id = :org_id AND project_id = ANY(:project_ids)`.
    A regression that dropped EITHER predicate would let a
    user's digest list events from another tenant's projects.
    Worst-class privacy bug — silent cross-tenant data exposure
    via outbound email.

  * **HTML injection.** Project names + event titles flow through
    `_html_escape` before landing in `<li>`. A regression that
    skipped escaping (a "let's just use f-string" simplification)
    would let a malicious project name execute script in the
    user's email client OR break the layout for everyone reading
    that org's digest.

  * **Module label drift.** `_MODULE_LABEL` maps wire identifiers
    to human-readable names. A rename of a value here AND on the
    wire silently disconnects the mapping — every event renders
    with the raw module ID instead of the friendly label.

  * **Cron-summary key drift.** `dispatch_daily_digests` returns
    `{candidates, sent, skipped_no_activity, deliveries}`. The
    arq cron logs this at INFO; any log-aggregator dashboard
    grouping on these keys breaks silently on a rename.

  * **`digest_for_user` signature drift.** Called positionally by
    `dispatch_daily_digests`; a kw rename would break the cron
    immediately (loud), but a default-value drift on `since_hours`
    would silently widen/narrow every digest's window.

This file is read-only — exercises pure rendering helpers + the
SQL invariants via source-grep. Survives reverts of
`services/notifications.py`.
"""

from __future__ import annotations

import inspect
import re
from collections import defaultdict
from uuid import UUID, uuid4

# ---------- Module presence ----------


def test_notifications_module_imports():
    """All public + private surfaces importable. Hard ImportError on
    revert = desired loud signal vs silent broken digest pipeline."""
    from services.notifications import (  # noqa: F401
        _DIGEST_SQL,
        _MODULE_LABEL,
        _html_escape,
        digest_for_user,
        dispatch_daily_digests,
    )


# ---------- Module label registry ----------


def test_module_label_set_pinned():
    """The 7 vertical labels. A rename here without updating the
    wire identifier (or vice versa) silently breaks the mapping —
    every event under the broken module renders as the raw module
    ID in the email."""
    from services.notifications import _MODULE_LABEL

    expected = {
        "pulse": "ProjectPulse",
        "siteeye": "SiteEye",
        "handover": "Handover",
        "winwork": "WinWork",
        "drawbridge": "Drawbridge",
        "costpulse": "CostPulse",
        "codeguard": "CodeGuard",
    }
    assert expected == _MODULE_LABEL, (
        f"_MODULE_LABEL drifted: have {_MODULE_LABEL}, want {expected}. "
        "A drift either renames the wire identifier (DIGEST_SQL emits "
        "literal strings — must match) or silently breaks the human "
        "label."
    )


def test_module_label_keys_match_digest_sql_emitted_modules():
    """Cross-pin: the modules emitted in `_DIGEST_SQL` (the literal
    strings in `'pulse'::text`, etc.) MUST be a subset of
    `_MODULE_LABEL.keys()`. Otherwise an event renders without a
    label and falls through to the raw wire identifier.

    The reverse direction (extra labels with no SQL emitter) is
    fine — a label reserved for a future module is harmless.
    """
    from services.notifications import _DIGEST_SQL, _MODULE_LABEL

    # Find every `'<word>'::text AS module` literal in the SQL.
    matches = re.findall(r"'(\w+)'::text\s+AS\s+module", _DIGEST_SQL)
    # Plus the bare-string forms `'<word>'` used after the first row.
    bare_matches = re.findall(r"\bUNION ALL\s+SELECT\s+id,\s+project_id,\s+'(\w+)'", _DIGEST_SQL)
    sql_modules = set(matches) | set(bare_matches)

    missing_label = sql_modules - set(_MODULE_LABEL.keys())
    assert not missing_label, (
        f"_DIGEST_SQL emits modules with no _MODULE_LABEL entry: "
        f"{missing_label}. Events from these modules render as the raw "
        "wire identifier in the digest email."
    )


# ---------- Cross-tenant SQL invariants ----------


def test_digest_sql_filters_every_branch_by_organization_id():
    """SECURITY-CRITICAL pin. Every UNION ALL branch in the digest
    SQL MUST filter by `organization_id = :org_id`. A regression
    that dropped this predicate from any single branch would let
    that module's events leak across tenants in the daily digest —
    the worst-class data leak (outbound email, attributed to us).
    """
    from services.notifications import _DIGEST_SQL

    # Each WHERE block in the UNION ALL chain. Find them by the
    # `WHERE organization_id = :org_id` substring count.
    org_filter_count = _DIGEST_SQL.count("organization_id = :org_id")

    # Count the branches by `UNION ALL` (= n-1) plus the first
    # SELECT.
    union_count = _DIGEST_SQL.count("UNION ALL")
    expected_branches = union_count + 1

    assert org_filter_count == expected_branches, (
        f"_DIGEST_SQL has {expected_branches} UNION ALL branches but "
        f"only {org_filter_count} `organization_id = :org_id` filters. "
        "Cross-tenant data leak: a branch missing the org filter would "
        "include other tenants' rows in the digest."
    )


def test_digest_sql_filters_every_branch_by_project_id_array():
    """The user-watches scoping. Every branch MUST filter by
    `project_id = ANY(:project_ids)` so the user only sees events
    from projects they explicitly watch. A regression that dropped
    this would email the user the org's ENTIRE activity feed for
    24h — privacy regression even within one tenant."""
    from services.notifications import _DIGEST_SQL

    project_filter_count = _DIGEST_SQL.count("project_id = ANY(:project_ids)")
    union_count = _DIGEST_SQL.count("UNION ALL")
    expected_branches = union_count + 1

    assert project_filter_count == expected_branches, (
        f"_DIGEST_SQL has {expected_branches} UNION ALL branches but "
        f"only {project_filter_count} project_id-array filters. "
        "Without the watch-scoped filter, users get the org's entire "
        "activity feed in their digest — privacy regression."
    )


def test_digest_sql_filters_every_branch_by_since_window():
    """The 24h-window scoping. Every branch MUST filter on its
    timestamp column `>= :since`. A regression that dropped this
    on any branch would email the user EVERY historical event in
    that module — multi-megabyte digest emails, customer rage."""
    from services.notifications import _DIGEST_SQL

    # Different branches use different timestamp columns
    # (created_at, completed_at, detected_at, reported_at,
    # delivered_at). Just count `>= :since` literal occurrences.
    since_filter_count = _DIGEST_SQL.count(">= :since")
    union_count = _DIGEST_SQL.count("UNION ALL")
    expected_branches = union_count + 1

    assert since_filter_count >= expected_branches, (
        f"_DIGEST_SQL has {expected_branches} UNION ALL branches but "
        f"only {since_filter_count} `>= :since` window filters. A "
        "branch missing the window would email the user every "
        "historical event in that module."
    )


def test_digest_sql_caps_total_events_at_200():
    """The trailing `LIMIT 200` caps the email size. A regression
    that lifted the cap (or removed it) would let a busy project
    produce a multi-MB email — most providers reject those
    silently."""
    from services.notifications import _DIGEST_SQL

    assert "LIMIT 200" in _DIGEST_SQL, (
        "_DIGEST_SQL no longer caps results at 200 events. A busy "
        "tenant could produce a multi-MB email payload, which most "
        "SMTP relays reject silently."
    )


def test_digest_sql_orders_by_timestamp_desc():
    """The list ordering. Newest events first. A regression to ASC
    would put the user's morning's events at the bottom of a
    LIMIT-200 list, losing the most-recent activity first."""
    from services.notifications import _DIGEST_SQL

    assert "ORDER BY timestamp DESC" in _DIGEST_SQL, (
        "_DIGEST_SQL no longer orders newest-first. A LIMIT 200 over "
        "ASC would discard the most-recent (most relevant) events."
    )


# ---------- HTML escape ----------


def test_html_escape_handles_xss_vectors():
    """SECURITY-CRITICAL pin. The escape MUST handle all four basic
    XSS vectors: `<`, `>`, `&`, `"`. A project named
    `<script>alert(1)</script>` MUST render as text in the email,
    not execute. (Most modern email clients disable script anyway,
    but defense-in-depth — and the layout-break risk is real:
    `</li>` in a project name without escape would shatter the
    bullet list.)
    """
    from services.notifications import _html_escape

    payload = '<script>alert("xss")</script>'
    out = _html_escape(payload)
    assert "<script>" not in out
    assert "&lt;script&gt;" in out
    assert '"xss"' not in out  # the quote was escaped
    assert "&quot;xss&quot;" in out


def test_html_escape_preserves_safe_text():
    """Plain text passes through unchanged. A regression that
    over-escaped (e.g. URL-encoded everything) would render
    project names like `%C3%A0` instead of `à` in the email."""
    from services.notifications import _html_escape

    assert _html_escape("Hà Nội Tower") == "Hà Nội Tower"
    assert _html_escape("Project 42") == "Project 42"


def test_html_escape_handles_ampersand_first():
    """Order matters: `&` MUST be escaped FIRST so a literal `&amp;`
    in the input doesn't get double-escaped to `&amp;amp;`. A
    regression that swapped the order would silently produce
    double-escaped output for any input containing already-escaped
    HTML."""
    from services.notifications import _html_escape

    # If the implementation escapes `&` last, `<` would become
    # `&lt;` first, then the `&` in `&lt;` would re-escape to
    # `&amp;lt;`.
    out = _html_escape("<")
    assert out == "&lt;", (
        f"_html_escape produced {out!r} for `<`. Either the order "
        "is wrong (`&` escaped after `<`, doubling) or a basic "
        "vector is missing."
    )


# ---------- digest_for_user behaviour ----------


def test_digest_for_user_returns_none_for_empty_project_set():
    """A user with no watched projects is a no-op. Returns None so
    the cron skips them WITHOUT issuing the SQL. Defends against
    `project_id = ANY('{}')` being interpreted as "all projects"
    by some PG versions (it isn't, but the early-return is the
    safer code path).
    """
    import asyncio

    from services.notifications import digest_for_user

    out = asyncio.run(
        digest_for_user(
            session=None,  # type: ignore[arg-type]
            organization_id=uuid4(),
            user_id=uuid4(),
            user_email="user@example.com",
            project_ids_to_names={},  # empty
        )
    )
    assert out is None, (
        "digest_for_user did NOT short-circuit on empty project_ids. "
        "It would now issue a SQL query with empty project_ids — "
        "behaviour depends on PG version (might match every project "
        "in the org, cross-leaking)."
    )


def test_digest_for_user_signature_pinned():
    """Called from `dispatch_daily_digests` by keyword. A rename =
    TypeError on the next cron tick (loud), but pin the kw-only
    posture so a positional regression doesn't quietly slip in."""
    from services.notifications import digest_for_user

    assert inspect.iscoroutinefunction(digest_for_user)

    sig = inspect.signature(digest_for_user)
    params = list(sig.parameters.values())

    assert params[0].name == "session"
    kw_names = [p.name for p in params[1:]]
    assert kw_names == [
        "organization_id",
        "user_id",
        "user_email",
        "project_ids_to_names",
        "since_hours",
    ], f"digest_for_user keyword block drifted: {kw_names}"

    # `since_hours` defaults to 24 — the daily digest's window. A
    # drift to 48 silently doubles every email's content.
    assert sig.parameters["since_hours"].default == 24, (
        f"digest_for_user.since_hours default drifted to "
        f"{sig.parameters['since_hours'].default}. The daily-cadence "
        "cron expects 24h windows; a drift causes overlap (re-emailing) "
        "or gaps (missing events)."
    )


# ---------- dispatch_daily_digests cron summary ----------


def test_dispatch_daily_digests_signature_pinned():
    """Called from `workers.queue.daily_activity_digest_cron` with a
    single positional session arg. A signature change would break
    the cron's invocation."""
    from services.notifications import dispatch_daily_digests

    assert inspect.iscoroutinefunction(dispatch_daily_digests)
    sig = inspect.signature(dispatch_daily_digests)
    params = list(sig.parameters.keys())
    assert params == ["session"], (
        f"dispatch_daily_digests signature drifted: {params}. The "
        "cron passes a session positionally; rename = TypeError."
    )


def test_dispatch_summary_keys_documented():
    """The cron logs the return at INFO. Any log-aggregator dashboard
    grouping on these keys breaks silently on a rename. We pin via
    source-grep — actually invoking the function needs DB+SMTP
    fixtures we don't want here."""
    import services.notifications as mod

    src = inspect.getsource(mod.dispatch_daily_digests)

    # All four documented keys appear in the return statement.
    for key in ("candidates", "sent", "skipped_no_activity", "deliveries"):
        assert f'"{key}"' in src, (
            f"dispatch_daily_digests no longer emits the {key!r} key in "
            "its return summary. Log-aggregator dashboards grouping on "
            "this key would silently break."
        )


# ---------- Per-project grouping order ----------


def test_render_text_groups_by_project():
    """The plain-text renderer emits one section per project, in the
    insertion order of `by_project`. A regression that flat-listed
    every event chronologically would lose the "skim by project"
    UX the renderer was built for.

    We exercise the renderer directly with synthetic data — pure
    function, no DB needed.
    """
    from datetime import datetime as _dt

    from services.notifications import _render_text

    pid_a = UUID("00000000-0000-0000-0000-000000000001")
    pid_b = UUID("00000000-0000-0000-0000-000000000002")

    events_a = [
        {
            "module": "pulse",
            "title": "Task done: foo",
            "timestamp": _dt(2026, 5, 9, 10, 0),
        },
    ]
    events_b = [
        {
            "module": "siteeye",
            "title": "Safety incident: slip",
            "timestamp": _dt(2026, 5, 9, 11, 0),
        },
    ]

    by_project: dict[UUID, list[dict]] = defaultdict(list)
    by_project[pid_a].extend(events_a)
    by_project[pid_b].extend(events_b)
    names = {pid_a: "Tower A", pid_b: "Tower B"}

    out = _render_text(by_project, names, since_hours=24)

    # Both project headings appear; A comes before B (insertion order).
    assert "## Tower A" in out
    assert "## Tower B" in out
    assert out.index("## Tower A") < out.index("## Tower B"), (
        "_render_text reordered projects from insertion order. "
        "The 'skim by project' UX depends on stable per-section grouping."
    )

    # Each event's friendly module label appears (NOT the raw wire id).
    assert "ProjectPulse" in out
    assert "SiteEye" in out
    assert "[pulse]" not in out, (
        "_render_text leaked the raw module identifier `pulse` into "
        "the output. _MODULE_LABEL lookup is broken or skipped."
    )
