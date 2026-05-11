"""Pin the `routers/webhooks.py` partner-facing surface.

This is the customer-controlled webhook subscription endpoint.
Distinct from `routers/webhook_deliveries_admin.py` (the
cross-tenant ops view I pinned earlier) — this router is what
the customer's admin clicks "Add webhook" against, and what their
integration partner reads via `GET /api/v1/webhooks` to know
which subscriptions exist.

Known revert target. The customer-facing endpoints have been
silently reverted multiple times in this codebase's history;
this pin is the tripwire that makes the next revert fail CI
loudly instead of silently breaking partner integrations.

What this file pins:

  * **Public `/event-types` is NOT auth-gated.** Partners
    evaluating the platform read it BEFORE getting an API key.
    A regression that added `Depends(require_auth)` would
    silently break the public partner-docs page.

  * **Every other endpoint requires `Role.ADMIN`.** A regression
    to `Role.MEMBER` (or `require_auth` alone) would let any org
    member rotate a webhook secret OR delete a peer's webhook —
    privacy + integration-trust violation.

  * **Idempotent route class wired in the router.** The
    `IdempotentRoute` ensures partner retries (after a network
    blip) don't double-create webhooks or double-fire test pings.
    A regression to plain `APIRouter` would silently break
    retry-safety.

  * **Path set + per-path methods stable.** Customer integration
    tests AND the partner-docs page hardcode these URLs. Renames
    silently 404 every existing partner.

  * **`/event-types` returns a sorted list.** The frontend
    partner-docs page renders alphabetically without re-sorting
    in JS. A regression that emitted unsorted output would
    silently change the docs ordering.

This file is read-only — inspects router declarations + handler
sources without invoking handlers (which need DB sessions). Survives
reverts.
"""

from __future__ import annotations

import inspect

# ---------- Module + router presence ----------


def test_webhooks_router_module_imports():
    """Module + `router` attribute. ImportError on revert =
    desired loud signal."""
    from routers import webhooks  # noqa: F401
    from routers.webhooks import router  # noqa: F401


def test_webhooks_router_prefix_pinned():
    """`/api/v1/webhooks` is the documented partner-facing prefix.
    Partner integration code hardcodes this; rename silently 404s
    every customer's webhook configuration UI."""
    from routers.webhooks import router

    assert router.prefix == "/api/v1/webhooks", (
        f"webhooks router prefix drifted to {router.prefix!r}. "
        "Customer integrations hardcode /api/v1/webhooks; rename "
        "silently 404s every webhook config screen."
    )


def test_webhooks_router_uses_idempotent_route_class():
    """The router is constructed with `route_class=IdempotentRoute`
    so partner retries (network blip + retry) don't double-create
    subscriptions or double-fire test pings.

    A regression to plain `APIRouter()` would silently break
    retry-safety — every duplicate retry that used to be cached
    would now run twice.
    """
    import routers.webhooks as mod

    src = inspect.getsource(mod)
    assert "route_class=IdempotentRoute" in src, (
        "webhooks router no longer uses route_class=IdempotentRoute. "
        "Partner retries can now create duplicate subscriptions or "
        "fire double test deliveries — silent retry-safety regression."
    )


# ---------- Path coverage ----------


def test_webhooks_router_exposes_documented_paths():
    """Pin the canonical path set. Partner-docs + customer
    integration tests hardcode these — a rename silently 404s
    every existing integration."""
    from routers.webhooks import router

    paths = {r.path for r in router.routes}

    expected = {
        "/api/v1/webhooks/event-types",  # public catalog
        "/api/v1/webhooks",  # POST create + GET list
        "/api/v1/webhooks/{webhook_id}",  # PATCH + DELETE
        "/api/v1/webhooks/{webhook_id}/rotate-secret",
        "/api/v1/webhooks/{webhook_id}/test",
        "/api/v1/webhooks/{webhook_id}/deliveries",
        "/api/v1/webhooks/{webhook_id}/deliveries/histogram",
        "/api/v1/webhooks/deliveries/dead-letter",
        "/api/v1/webhooks/deliveries/{delivery_id}/redeliver",
    }

    missing = expected - paths
    assert not missing, (
        f"webhooks router lost paths: {missing}. Existing partner integrations would 404 on these. All paths: {paths}"
    )


def test_event_types_endpoint_method_is_get_only():
    """Read-only — the catalog is a static description of what
    we emit. A POST/PUT regression here would expose mutation
    routes against documentation."""
    from routers.webhooks import router

    event_types_route = next(r for r in router.routes if getattr(r, "path", None) == "/api/v1/webhooks/event-types")
    methods = set(event_types_route.methods or [])
    assert methods.issubset({"GET", "HEAD"}), (
        f"/event-types exposes {methods}; want GET-only. The catalog "
        "is static documentation; a mutation route here would be a "
        "categorical surprise."
    )


# ---------- Public access on /event-types ----------


def test_event_types_endpoint_has_no_auth_dep():
    """SECURITY-RELEVANT pin (in BOTH directions). The
    `/event-types` catalog is intentionally PUBLIC — partners
    evaluating the platform read it before getting an API key. A
    regression that gated it would silently break the partner-docs
    page (the public-evaluation path).

    Pin via source-grep for the absence of `Depends(require_*)` on
    the handler. The introspection-via-FastAPI route would be
    cleaner but `app.routes` requires the full app to be mounted.
    """
    import routers.webhooks as mod

    src = inspect.getsource(mod.list_event_types)
    # The handler signature MUST NOT reference any auth dep.
    assert "require_min_role" not in src, (
        "list_event_types handler now references require_min_role. "
        "The /event-types catalog is intentionally public for "
        "partner evaluation — gating it breaks the public docs page."
    )
    assert "require_auth" not in src, (
        "list_event_types handler now references require_auth. "
        "Catalog is public; auth gate would block partner evaluators."
    )
    assert "require_user" not in src


# ---------- Admin gating on every other endpoint ----------


_HANDLER_NAMES_THAT_MUST_BE_ADMIN_GATED = (
    "create_webhook",
    "list_webhooks",
    "update_webhook",
    "delete_webhook",
    "rotate_webhook_secret",
    "test_webhook",
    "list_deliveries",
    "deliveries_histogram",
    "list_dead_letter",
    "redeliver",
)


def test_every_mutating_endpoint_requires_admin_role():
    """SECURITY-CRITICAL pin. Every webhook handler EXCEPT
    `list_event_types` MUST gate on `Role.ADMIN`. A regression to
    `Role.MEMBER` (or `require_auth` alone) would let any org
    member:

      * Rotate a peer admin's webhook secret (integration breakage)
      * Delete a peer's webhook subscription (silent integration loss)
      * Re-fire a delivery that touches another team's data
        (cross-team trust violation within the org)

    Pin via source-grep on each handler's source. We DON'T inspect
    `route.dependant.dependencies` because that requires constructing
    the full FastAPI app (drags in DB + Redis dep init).
    """
    import routers.webhooks as mod

    for handler_name in _HANDLER_NAMES_THAT_MUST_BE_ADMIN_GATED:
        handler = getattr(mod, handler_name, None)
        assert handler is not None, (
            f"Handler `{handler_name}` is missing from routers/webhooks.py. "
            "Either it was renamed (update this pin) or removed (silent "
            "endpoint loss; partner integrations 404)."
        )

        src = inspect.getsource(handler)
        assert "require_min_role(Role.ADMIN)" in src, (
            f"Handler `{handler_name}` no longer gates on "
            "`require_min_role(Role.ADMIN)`. SECURITY: a downgrade "
            "to MEMBER lets non-admin org users mutate webhooks; a "
            "swap to require_auth lets ANY logged-in user (other-org "
            "users hitting the URL) get further than the org-membership "
            "check."
        )


# ---------- Per-handler shape ----------


def test_create_webhook_returns_secret_once():
    """The CREATE endpoint returns the generated secret in its
    response. This is the ONLY time the customer sees the secret —
    subsequent reads MUST mask it. A regression that omitted the
    secret from the create-response would orphan the subscription
    (customer can't compute HMAC for incoming pings).
    """
    import routers.webhooks as mod

    src = inspect.getsource(mod.create_webhook)
    # The schema returned MUST be `WebhookSubscriptionCreated` (the
    # variant that includes the secret), not the secret-stripped
    # `WebhookSubscriptionOut`.
    assert "WebhookSubscriptionCreated" in src, (
        "create_webhook no longer returns WebhookSubscriptionCreated "
        "(the secret-bearing schema). Customers can't compute HMAC "
        "without the secret — the subscription is orphan-on-arrival."
    )
    # The secret value comes from `generate_secret()` not e.g. a
    # hardcoded fallback.
    assert "generate_secret()" in src, (
        "create_webhook no longer calls generate_secret(). A "
        "regression here could either reuse a stale secret or "
        "skip secret generation entirely."
    )


def test_create_webhook_409s_on_duplicate_url():
    """Idempotent on `(org, url)` via PG UNIQUE constraint. Re-
    POSTing the same URL surfaces 409 instead of silently rotating
    the secret. A regression that swallowed `IntegrityError` would
    let duplicate POST quietly succeed (with a NEW secret), which
    would silently invalidate the customer's existing integration."""
    import routers.webhooks as mod

    src = inspect.getsource(mod.create_webhook)
    assert "IntegrityError" in src, (
        "create_webhook no longer catches IntegrityError. A "
        "duplicate-URL POST would 500 instead of returning 409 "
        "with a friendly conflict message."
    )
    assert "HTTP_409_CONFLICT" in src, (
        "create_webhook no longer returns 409 on duplicate URL. "
        "A change to 200 (silent overwrite) would invalidate the "
        "customer's existing integration on every re-POST."
    )


def test_create_webhook_attributes_to_caller_org():
    """SECURITY-CRITICAL pin. The new subscription's
    `organization_id` MUST come from `auth.organization_id` — NOT
    a request-body field. A regression that read it from the body
    would let a partner mint webhooks against another tenant.
    """
    import routers.webhooks as mod

    src = inspect.getsource(mod.create_webhook)
    assert "organization_id=auth.organization_id" in src, (
        "create_webhook no longer binds organization_id from "
        "auth.organization_id. SECURITY: if the org id comes from "
        "the request body, a partner could subscribe to webhooks "
        "for another tenant's events."
    )


def test_event_types_endpoint_returns_sorted_list():
    """Frontend renders alphabetically without re-sorting in JS.
    A regression to dict-iteration order would silently change
    the docs ordering on every redeploy."""
    import routers.webhooks as mod

    src = inspect.getsource(mod.list_event_types)
    assert "sorted(" in src, (
        "list_event_types no longer sorts its output. The partner-"
        "docs page renders the list in API-response order — "
        "without sort, ordering is dict-iteration-defined and "
        "drifts between deploys."
    )
    assert "key=lambda" in src or "key=" in src, (
        "list_event_types' sort lost its key function. The default "
        "sort by dict identity is meaningless — must sort by event_type."
    )


def test_redeliver_endpoint_is_post_with_202():
    """Re-firing a delivery is asynchronous (enqueues a job; doesn't
    wait for delivery). 202 Accepted is the right semantic. A
    regression to 200 OK would let callers think the delivery
    actually landed when it's still in the queue."""
    from routers.webhooks import router

    redeliver_route = next(
        r for r in router.routes if getattr(r, "path", None) == "/api/v1/webhooks/deliveries/{delivery_id}/redeliver"
    )
    methods = set(redeliver_route.methods or [])
    assert methods == {"POST"}, (
        f"redeliver route exposes {methods}; want POST. A GET would "
        "make the action idempotent-by-URL (every page refresh "
        "re-fires the delivery)."
    )
    # The status code is set on the route's `status_code` attribute
    # (FastAPI captures the decorator's `status_code=` kwarg).
    assert redeliver_route.status_code == 202, (
        f"redeliver route status_code is {redeliver_route.status_code}; "
        "want 202 Accepted (the action is async — enqueues a job, "
        "doesn't wait for delivery)."
    )


def test_test_webhook_endpoint_uses_202_status():
    """Same async-enqueue semantics as redeliver. A test ping is
    enqueued + drained by the cron, not synchronously sent."""
    from routers.webhooks import router

    test_route = next(r for r in router.routes if getattr(r, "path", None) == "/api/v1/webhooks/{webhook_id}/test")
    assert test_route.status_code == 202, (
        f"test_webhook status_code is {test_route.status_code}; "
        "want 202. A test ping is async (enqueue + drain), not "
        "synchronous."
    )


def test_delete_webhook_endpoint_uses_204():
    """DELETE returns 204 No Content — REST convention for
    successful delete. A regression to 200 would force the caller
    to handle a body that isn't there."""
    from routers.webhooks import router

    delete_route = next(
        r
        for r in router.routes
        if getattr(r, "path", None) == "/api/v1/webhooks/{webhook_id}" and "DELETE" in (r.methods or set())
    )
    assert delete_route.status_code == 204, (
        f"DELETE webhook status_code is {delete_route.status_code}; want 204 No Content."
    )


def test_list_webhooks_does_not_expose_secret():
    """SECURITY-CRITICAL pin. The list endpoint MUST return the
    secret-stripped `WebhookSubscriptionOut`, NOT the
    secret-bearing `WebhookSubscriptionCreated`. The secret is
    shown ONCE (at create); a list endpoint that emitted it would
    leak every subscription's signing secret to anyone who could
    GET the list (even a legitimate admin, the secret should be
    write-once read-never).
    """
    import routers.webhooks as mod

    src = inspect.getsource(mod.list_webhooks)
    assert "WebhookSubscriptionCreated" not in src, (
        "list_webhooks now references WebhookSubscriptionCreated. "
        "That schema includes the secret — a list endpoint emitting "
        "it would leak every webhook's signing secret on every read."
    )


def test_rotate_webhook_secret_returns_new_secret():
    """The ONE other place a webhook secret is exposed is on
    rotate-secret. The handler delegates to
    `services.webhooks.rotate_secret` and returns a dict that
    includes the new `secret` value — customers need it to update
    their HMAC verifier; omitting it would leave the customer's
    integration broken after every rotation.

    Pin the contract:
      * Delegates to the service-layer `rotate_secret` helper
        (not inlined in the route handler).
      * Returns a body containing `"secret":` (the new value, shown
        ONCE — no read-after endpoint).
      * Returns the documented `grace_seconds` field for the dual-
        signature rollover window.
      * Audits the rotation via `webhooks.subscription.rotate_secret`.
    """
    import routers.webhooks as mod

    src = inspect.getsource(mod.rotate_webhook_secret)

    # Delegated to the service-layer helper.
    assert "rotate_secret(" in src, (
        "rotate_webhook_secret no longer delegates to the "
        "services.webhooks.rotate_secret helper. The handler should "
        "stay thin; inlining the rotation logic risks divergence "
        "with the dispatcher's grace-window code."
    )
    # New secret surfaced in the response body.
    assert '"secret":' in src or '"secret"' in src, (
        "rotate_webhook_secret no longer returns the new secret "
        "in the response body. Customer's HMAC verifier stays "
        "stuck on the old secret, breaking the integration."
    )
    # Grace-seconds field — dual-signature rollover window.
    assert "grace_seconds" in src, (
        "rotate_webhook_secret no longer surfaces grace_seconds. "
        "The customer needs to know how long the OLD secret keeps "
        "verifying so they can roll forward without downtime."
    )
    # Audit row is written.
    assert '"webhooks.subscription.rotate_secret"' in src or "'webhooks.subscription.rotate_secret'" in src, (
        "rotate_webhook_secret no longer writes an audit row. "
        "Admins answering 'did someone rotate this in the last "
        "incident?' lose the durable record."
    )


# ---------- IdempotentRoute import ----------


def test_idempotent_route_class_imported_from_known_path():
    """The route class import MUST come from
    `middleware.idempotency_route` (the canonical location in this
    codebase). A drift to a stub/mock import path would silently
    disable retry-safety without the `route_class=` argument
    changing — the imported `IdempotentRoute` symbol would resolve
    to a no-op route class while the router constructor still
    looks correct.
    """
    import routers.webhooks as mod

    src = inspect.getsource(mod)
    assert "from middleware.idempotency_route import IdempotentRoute" in src, (
        "webhooks router no longer imports IdempotentRoute from "
        "middleware.idempotency_route. A regression to a stub "
        "import would silently disable retry-safety while leaving "
        "route_class=IdempotentRoute looking correct in the router "
        "constructor."
    )
