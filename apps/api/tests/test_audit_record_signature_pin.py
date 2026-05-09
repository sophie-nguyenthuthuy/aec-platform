"""Pin the signature of `services.audit.record()`.

Why this exists: this function's parameter list has flipped between
two shapes across recent batches — in particular, the actor
parameter alternates between `actor_user_id: UUID | None` (the
older form) and `auth: AuthContext | None` (the newer form). Each
flip breaks every callsite — `routers/admin.py`, `routers/notifications.py`,
`routers/costpulse.py`, `workers/queue.py` etc. all silently 500 at
runtime against the wrong shape.

Pinning the signature catches the flip at test-collection time
rather than at customer-traffic time. The breakage is a
caller-vs-callee mismatch: the call sites use named kwargs (`auth=auth`
or `actor_user_id=auth.user_id`), and the signature flip means the
unexpected one becomes a TypeError at runtime.

If you intentionally change `record()`'s signature, update
`EXPECTED_PARAMS` below in the same PR + audit every callsite.
The sweep is small — a `grep -rn "audit\\.record\\|record(" apps/api`
catches them all.
"""

from __future__ import annotations

import inspect

from services.audit import record

# Source of truth, pinned 2026-05-04. Each entry is
# `(name, kind, default_is_required)`. The annotation isn't pinned
# here because annotation strings drift across Python versions
# (`UUID | None` vs `Optional[UUID]`); the kind + default are the
# load-bearing part for caller compatibility.
EXPECTED_PARAMS: list[tuple[str, str, bool]] = [
    # `session` is the FIRST positional — every caller passes it
    # positionally, so a rename is safe but a reorder breaks
    # everyone.
    ("session", "POSITIONAL_OR_KEYWORD", True),
    # Org scope — required keyword. The audit row's tenant
    # attribution lives here.
    ("organization_id", "KEYWORD_ONLY", True),
    # Actor context — `auth: AuthContext | None`. None for system
    # / cron-driven events. PINNED AS THE CURRENT NAME (`auth`,
    # not `actor_user_id`) — the flip between the two has been
    # the canonical regression this test catches.
    ("auth", "KEYWORD_ONLY", True),
    # The closed-set verb identifying what was done.
    ("action", "KEYWORD_ONLY", True),
    # What kind of resource (estimates, change_orders, etc.) +
    # which row.
    ("resource_type", "KEYWORD_ONLY", True),
    ("resource_id", "KEYWORD_ONLY", True),
    # Optional before/after JSON diffs. Default None (not {}) so
    # the audit row stores empty {} only when callers explicitly
    # pass {} — distinguishing "no diff" from "system event."
    ("before", "KEYWORD_ONLY", False),
    ("after", "KEYWORD_ONLY", False),
    # Optional Request — for IP / User-Agent capture. Defaults to
    # None for cron callers + test contexts.
    ("request", "KEYWORD_ONLY", False),
]


def _signature_summary() -> list[tuple[str, str, bool]]:
    """Reduce `inspect.signature(record)` to the (name, kind, required)
    tuple shape `EXPECTED_PARAMS` uses. `required` is True when the
    parameter has no default value.
    """
    sig = inspect.signature(record)
    out: list[tuple[str, str, bool]] = []
    for name, p in sig.parameters.items():
        required = p.default is inspect.Parameter.empty
        out.append((name, p.kind.name, required))
    return out


def test_audit_record_signature_matches_pin_exactly():
    """Hard equality on the parameter list. Order matters because
    the first parameter (`session`) is passed positionally by every
    caller; everything else is keyword-only by design.
    """
    actual = _signature_summary()
    assert actual == EXPECTED_PARAMS, (
        "services.audit.record() signature drifted from the pinned shape.\n"
        f"  expected: {EXPECTED_PARAMS}\n"
        f"  actual:   {actual}\n"
        "If this is intentional, update EXPECTED_PARAMS + audit every "
        "callsite (`grep -rn 'audit\\.record' apps/api/routers apps/api/workers`)."
    )


def test_audit_record_actor_parameter_is_named_auth():
    """Pin the actor-parameter name explicitly. Two reasons:

    1. The flip between `actor_user_id` and `auth` has been the
       canonical regression — surfacing "the actor parameter has
       the wrong name" as a dedicated test makes the failure
       obvious without diffing the EXPECTED_PARAMS tuple.
    2. The semantic shift (one UUID vs. a full AuthContext that
       can route to api_key vs. user actor) has different
       downstream behavior — every callsite has to opt into the
       new shape, not migrate by happy accident.
    """
    sig = inspect.signature(record)
    assert "auth" in sig.parameters, (
        "services.audit.record() doesn't accept an `auth=` parameter. "
        "Recent reverts have re-introduced the older `actor_user_id=` form; "
        "if that's intentional, this test (and EXPECTED_PARAMS above) need to "
        "flip back too. Either way, audit every callsite for the matching "
        "kwarg shape."
    )
    assert "actor_user_id" not in sig.parameters, (
        "services.audit.record() still has the old `actor_user_id=` parameter. "
        "Either remove it or update this pin to the post-revert state."
    )


def test_audit_record_returns_audit_event():
    """The function should return a freshly-constructed `AuditEvent`
    instance. Test by inspecting the return-annotation; the actual
    construction is exercised in the integration tests.
    """
    sig = inspect.signature(record)
    return_annotation = sig.return_annotation
    # Annotation is a string under `from __future__ import annotations`
    # — inspect.signature returns the string verbatim. Match either
    # the bare class name or the dotted form.
    rendered = str(return_annotation)
    assert "AuditEvent" in rendered, (
        f"services.audit.record() should return an AuditEvent; return annotation is {rendered!r}"
    )
