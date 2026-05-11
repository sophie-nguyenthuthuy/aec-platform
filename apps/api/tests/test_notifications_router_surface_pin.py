"""Pin the `routers/notifications.py` user-preference + watch
surface.

Known revert target. The endpoints here are GDPR / VN PDPL-bearing
(opt-out toggles for marketing-style notifications), AND drive the
cron-side notification pipelines (the watch list IS the digest
recipient query). Distinct failure modes a regression here can
produce:

  * **Cross-user data exposure.** Every endpoint MUST filter by
    `auth.user_id` AND `auth.organization_id`. A regression that
    dropped EITHER would either leak peer users' watches/prefs
    OR let a user CRUD on another user's row.

  * **Silent opt-out failure.** If `upsert_preference` fails to
    audit the toggle, GDPR/PDPL "show me when my opt-out was
    recorded" requests can't be answered. The preference row
    still exists in the DB — but the audit log loses the
    "Alice turned email OFF for scraper_drift on 2026-05-09"
    breadcrumb.

  * **Race-unsafe CREATE.** Two concurrent POST /watches with
    the same project_id MUST NOT 500. The `IntegrityError`
    fallback path is what makes the endpoint idempotent under
    race; a regression that dropped it would expose the user
    to flaky create-watch on double-click.

  * **DELETE not idempotent.** `DELETE /watches/{project_id}`
    on a non-existent watch MUST return 204, not 404 — the
    desired end state is "you're not watching it" either way.
    A regression to 404 would surface as "tried to unwatch but
    got an error" in the UI.

  * **`before` audit snapshot AFTER mutation.** The audit row's
    `before` MUST be the value PRIOR to the upsert — not the
    post-update value. A regression that read `before` after the
    write would log every audit row as `before == after` (the
    state at the moment of audit), losing the "who changed what
    to what" breadcrumb.

This file is read-only — exercises router declarations + handler
sources. Survives reverts.
"""

from __future__ import annotations

import inspect

# ---------- Module + router presence ----------


def test_notifications_router_imports():
    from routers import notifications  # noqa: F401
    from routers.notifications import router  # noqa: F401


def test_notifications_router_prefix_pinned():
    """`/api/v1/notifications` is the documented prefix. Frontend
    `useWatches` + `usePreferences` hooks hardcode this; rename
    silently 404s the settings UI."""
    from routers.notifications import router

    assert router.prefix == "/api/v1/notifications", f"notifications router prefix drifted to {router.prefix!r}"


# ---------- Path coverage ----------


def test_notifications_router_exposes_documented_paths():
    """5 paths drive the user-facing notifications surface.
    Frontend hooks hardcode them; rename = 404."""
    from routers.notifications import router

    paths = {r.path for r in router.routes}

    expected = {
        "/api/v1/notifications/watches",  # GET list + POST create
        "/api/v1/notifications/watches/{project_id}",  # DELETE
        "/api/v1/notifications/preferences",  # GET list
        "/api/v1/notifications/preferences/{key}",  # PUT upsert
    }
    missing = expected - paths
    assert not missing, (
        f"notifications router lost paths: {missing}. Frontend "
        f"hooks hardcode these; rename silently 404s. All paths: {paths}"
    )


def test_create_watch_uses_201():
    """REST convention. Frontend distinguishes 201 (newly created)
    from 200 (idempotent re-watch returns the existing row). A
    regression to 200 on the create path would force the frontend
    to re-derive newness from row timestamps."""
    from routers.notifications import router

    # POST /watches → 201
    create_route = next(
        r
        for r in router.routes
        if getattr(r, "path", None) == "/api/v1/notifications/watches" and "POST" in (r.methods or set())
    )
    assert create_route.status_code == 201


def test_delete_watch_uses_204():
    """DELETE returns 204 No Content. Frontend reads the status
    code, not the body."""
    from routers.notifications import router

    delete_route = next(
        r
        for r in router.routes
        if getattr(r, "path", None) == "/api/v1/notifications/watches/{project_id}" and "DELETE" in (r.methods or set())
    )
    assert delete_route.status_code == 204


# ---------- Auth dep present everywhere ----------


def test_every_endpoint_requires_auth():
    """SECURITY pin. Every handler MUST gate on `require_auth`.
    A regression that dropped the dep on any single endpoint would
    let unauthenticated callers list other users' watches OR
    flip another user's preference toggles.

    Pin via source-grep on each handler — `require_auth` MUST
    appear in the function signature."""
    import routers.notifications as mod

    handler_names = (
        "list_my_watches",
        "create_watch",
        "delete_watch",
        "list_preferences",
        "upsert_preference",
    )
    for name in handler_names:
        handler = getattr(mod, name, None)
        assert handler is not None, f"Handler `{name}` missing from routers/notifications.py."
        src = inspect.getsource(handler)
        assert "require_auth" in src, (
            f"Handler `{name}` no longer references require_auth. "
            "An unauthenticated caller could now CRUD this surface."
        )


# ---------- Per-user + per-org scoping ----------


def test_list_my_watches_filters_by_user_and_org():
    """SECURITY-CRITICAL pin. The watches query MUST filter by
    BOTH `auth.user_id` AND `auth.organization_id`. Dropping
    either:
      * Drop user_id → user sees every member's watches in their
        org. Worst case, a member can enumerate "is Alice
        watching project X" (privacy regression).
      * Drop organization_id → user sees their own watches across
        orgs. If they're a member of two orgs, they see both
        orgs' watch list mingled (cross-tenant data exposure).
    """
    import routers.notifications as mod

    src = inspect.getsource(mod.list_my_watches)
    assert "ProjectWatch.user_id == auth.user_id" in src, (
        "list_my_watches no longer filters by auth.user_id. Members would see peers' watches — privacy regression."
    )
    assert "ProjectWatch.organization_id == auth.organization_id" in src, (
        "list_my_watches no longer filters by auth.organization_id. "
        "Multi-org users see watches across orgs mingled — "
        "cross-tenant data exposure."
    )


def test_create_watch_validates_project_belongs_to_caller_org():
    """SECURITY-CRITICAL pin. Before inserting a watch, the
    handler verifies the project belongs to `auth.organization_id`.
    A regression that skipped this would let a user watch ANY
    project (including other tenants' projects, by guessing UUIDs).

    The check is documented as "RLS would also block, but we want
    a clean 404 instead of an opaque RLS error" — pin both the
    explicit check AND the 404 outcome."""
    import routers.notifications as mod

    src = inspect.getsource(mod.create_watch)
    assert "Project.organization_id == auth.organization_id" in src, (
        "create_watch no longer validates the project belongs to "
        "the caller's org. Users could watch other tenants' projects."
    )
    assert "HTTP_404_NOT_FOUND" in src, (
        "create_watch no longer returns 404 on cross-tenant project. "
        "An RLS error would surface as a 500 instead — opaque to the user."
    )


def test_create_watch_handles_race_via_integrity_error():
    """RACE-SAFETY pin. Two concurrent POSTs with the same
    project_id MUST NOT 500. The handler catches `IntegrityError`
    on the UNIQUE-constraint violation, rolls back, then re-reads
    the row that won. A regression that dropped the catch would
    surface as 500s on legitimate double-clicks."""
    import routers.notifications as mod

    src = inspect.getsource(mod.create_watch)
    assert "IntegrityError" in src, (
        "create_watch no longer catches IntegrityError. Concurrent "
        "POSTs (e.g. user double-click) would 500 instead of "
        "returning the row that won the race."
    )
    assert "rollback" in src, (
        "create_watch no longer rolls back the failed transaction. The next query in the session would block."
    )


def test_create_watch_idempotent_on_existing_row():
    """User clicking 'watch' twice on the same project MUST get
    the existing row back, not a duplicate (or an error). Pin
    the early-return branch."""
    import routers.notifications as mod

    src = inspect.getsource(mod.create_watch)
    # The idempotent re-read happens BEFORE the INSERT attempt.
    # Source-grep for the existing-row branch.
    assert "existing is not None" in src, (
        "create_watch lost its existing-row early-return. "
        "User's second click would attempt an INSERT (caught by "
        "IntegrityError, but with extra DB load)."
    )


def test_delete_watch_filters_by_user_and_org_and_is_idempotent():
    """SECURITY + UX pin. The DELETE filters by user_id AND
    organization_id (so a user can't delete another user's
    watch by guessing project_id), AND is idempotent (returns
    204 on missing row, NOT 404)."""
    import routers.notifications as mod

    src = inspect.getsource(mod.delete_watch)
    assert "ProjectWatch.user_id == auth.user_id" in src
    assert "ProjectWatch.organization_id == auth.organization_id" in src
    # The non-existent-row branch returns None (which becomes 204
    # via the route's status_code= decorator).
    assert "if watch is None:" in src and "return None" in src, (
        "delete_watch no longer treats missing row as a no-op. "
        "Frontend gets 404 on already-deleted rows — surfaces as "
        "'tried to unwatch but got an error.'"
    )


def test_list_preferences_filters_by_user_and_org():
    """Same security pin as watches list."""
    import routers.notifications as mod

    src = inspect.getsource(mod.list_preferences)
    assert "NotificationPreference.user_id == auth.user_id" in src
    assert "NotificationPreference.organization_id == auth.organization_id" in src


def test_upsert_preference_filters_by_user_and_org():
    """SECURITY pin. The upsert's pre-read query MUST filter by
    user_id AND organization_id; if either is missing, a user
    could read AND mutate another user's preference rows.
    """
    import routers.notifications as mod

    src = inspect.getsource(mod.upsert_preference)
    assert "NotificationPreference.user_id == auth.user_id" in src, (
        "upsert_preference no longer filters by auth.user_id on the pre-read. A user could mutate another user's prefs."
    )
    assert "NotificationPreference.organization_id == auth.organization_id" in src


# ---------- Audit pin (GDPR / PDPL bearing) ----------


def test_upsert_preference_audits_the_change():
    """COMPLIANCE pin. Notification opt-out changes are
    GDPR / VN PDPL-bearing — we want a durable record of when
    each user enabled/disabled each channel. A regression that
    dropped the audit call would silently break the "show me my
    opt-out audit trail" compliance request.
    """
    import routers.notifications as mod

    src = inspect.getsource(mod.upsert_preference)
    assert "record_audit" in src or "audit" in src.lower(), (
        "upsert_preference no longer writes an audit row. The "
        "opt-out timestamp is now lost — GDPR/PDPL audit trail "
        "broken."
    )
    # The action literal is what `tests/test_audit_action_literal_pin.py`
    # also pins — cross-pin: this handler MUST emit it.
    assert '"notifications.preference.update"' in src or "'notifications.preference.update'" in src, (
        "upsert_preference no longer uses the documented "
        "`notifications.preference.update` audit action. The "
        "AuditAction Literal pin separately requires this exact "
        "string; both have to move in lockstep."
    )


def test_upsert_preference_snapshots_before_state():
    """COMPLIANCE pin. The audit row's `before` MUST be the value
    PRIOR to the mutation. A regression that read `before` AFTER
    the write would log every audit row as `before == after`
    (the post-state both times), silently losing the "who flipped
    this from on→off" breadcrumb."""
    import routers.notifications as mod

    src = inspect.getsource(mod.upsert_preference)
    # The fix is to capture before_email/before_slack BEFORE the
    # mutation. Pin by source-grep — the variable names are part
    # of the contract.
    assert "before_email" in src or "before_diff" in src, (
        "upsert_preference no longer snapshots prior values before "
        "mutation. The audit row's `before` would now equal the "
        "post-update value — losing the change breadcrumb."
    )


def test_upsert_preference_validates_key_length():
    """The key column has a CHECK constraint at 64 chars (per
    migration). The handler validates BEFORE the INSERT to surface
    a clean 400 instead of a 500 from the DB constraint."""
    import routers.notifications as mod

    src = inspect.getsource(mod.upsert_preference)
    assert "len(key) > 64" in src, (
        "upsert_preference no longer validates key length. A "
        "65+-char key would 500 on the DB constraint instead of "
        "returning a clean 400 to the caller."
    )
    assert "HTTP_400_BAD_REQUEST" in src
