"""Pin the rotation-status projection on `WebhookSubscriptionOut`
(cycle P1).

The schema synthesises two fields from the model's raw
`secret_previous` + `secret_previous_expires_at` columns:

  * `secret_previous_active` — bool, mirrors the dispatcher's
    `_previous_secret_active` decision rule. Surfaces in the partner
    UI as a "grace ends in Xh" badge.
  * `secret_previous_grace_seconds_remaining` — int seconds. Drives
    the badge text so the partner sees concrete time-left.

If these drift from the wire-side dispatcher's emit decision, the UI
shows "grace active" while the dispatcher has stopped emitting the
second signature (or vice versa). Both are computed from the same
`(secret_previous, secret_previous_expires_at)` tuple by separate
helpers — same source columns, different read-paths — so the
correctness invariant is "both branches MUST decide the same way".

The tests below pin the schema branch. The dispatcher branch is
pinned in test_webhook_secret_rotation.py. A drift between them
would fail BOTH (one would expect active, the other inactive).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from schemas.webhooks import WebhookSubscriptionOut, _compute_rotation_status

# ---------- _compute_rotation_status (pure helper) ------------------


def test_no_previous_secret_yields_inactive_and_zero():
    """The default path — subscription has never rotated. Both fields
    must come back as their inactive defaults so the badge doesn't
    render and the partner UI doesn't promise a grace that doesn't
    exist."""
    assert _compute_rotation_status(secret_previous=None, expires_at=None) == (False, 0)
    # Even if expires_at is set but secret material is missing
    # (corrupt row, partial write), treat as inactive — can't sign
    # without the secret, so the dispatcher wouldn't emit anyway.
    future = datetime.now(UTC) + timedelta(hours=1)
    assert _compute_rotation_status(secret_previous=None, expires_at=future) == (False, 0)


def test_expired_grace_is_inactive():
    """Once the grace window closes, the dispatcher stops emitting the
    second signature — the projection must agree. Even one second
    past expiry → inactive, remaining=0. Same boundary as
    `_previous_secret_active`."""
    past = datetime.now(UTC) - timedelta(seconds=1)
    assert _compute_rotation_status(secret_previous="old-secret", expires_at=past) == (False, 0)


def test_active_window_yields_remaining_seconds():
    """Inside the grace, `active=True` and `remaining` is the seconds
    left until expiry. Frontend renders as "ends in Xh" — pin so a
    refactor that returns minutes / hours by mistake would surface."""
    future = datetime.now(UTC) + timedelta(hours=14)
    active, remaining = _compute_rotation_status(secret_previous="old", expires_at=future)
    assert active is True
    # Allow 5s of slop for the time between datetime.now() at
    # construction vs. the helper's internal datetime.now().
    assert 14 * 3600 - 5 <= remaining <= 14 * 3600 + 1, f"got {remaining}, expected ~{14 * 3600}"


def test_remaining_seconds_clamped_to_zero():
    """`max(0, ...)` clamp defends against a microsecond-level race
    where expires_at > now in the active branch but the subtraction
    rounds to a negative integer. Operationally never happens but
    pinning the floor avoids a future "why is remaining = -0?"
    triage."""
    # Use an expiry exactly equal to "now" (can't get to inactive
    # branch because the strict `<= now` check), and verify the
    # clamp via a delta ~0.
    barely_future = datetime.now(UTC) + timedelta(microseconds=1)
    active, remaining = _compute_rotation_status(secret_previous="old", expires_at=barely_future)
    # Either branch is acceptable here — the test pins remaining ≥ 0
    # in BOTH so the contract is bounded regardless.
    if active:
        assert remaining >= 0
    else:
        assert remaining == 0


# ---------- WebhookSubscriptionOut.model_validate roundtrip --------


def _orm_like(*, secret_previous: str | None, expires_at: datetime | None) -> SimpleNamespace:
    """Build a duck-typed object mimicking a `WebhookSubscription`
    ORM row. The schema's model_validator(mode='before') works
    against attribute access, so SimpleNamespace is fine."""
    return SimpleNamespace(
        id=uuid4(),
        url="https://example.com/hook",
        event_types=[],
        enabled=True,
        last_delivery_at=None,
        failure_count=0,
        created_at=datetime.now(UTC),
        secret_previous=secret_previous,
        secret_previous_expires_at=expires_at,
    )


def test_model_validate_from_orm_row_no_rotation():
    """A subscription that's never rotated → projection has
    `secret_previous_active=False`, `remaining=0`. Pin the default
    so a partner whose UI checks `if data.secret_previous_active`
    doesn't see a stale True from a previous render."""
    out = WebhookSubscriptionOut.model_validate(_orm_like(secret_previous=None, expires_at=None))
    assert out.secret_previous_active is False
    assert out.secret_previous_grace_seconds_remaining == 0


def test_model_validate_from_orm_row_active_rotation():
    """Mid-rotation subscription → projection surfaces both fields.
    The integer must be in seconds, not minutes/hours — frontend
    formatter does the unit conversion."""
    future = datetime.now(UTC) + timedelta(hours=14)
    out = WebhookSubscriptionOut.model_validate(_orm_like(secret_previous="x" * 64, expires_at=future))
    assert out.secret_previous_active is True
    assert 14 * 3600 - 5 <= out.secret_previous_grace_seconds_remaining <= 14 * 3600 + 1


def test_model_validate_never_includes_secret_columns_in_dump():
    """Defense in depth: even though the model carries `secret`,
    `secret_previous`, `secret_previous_expires_at`, the projection
    MUST NOT expose any of them. A regression that propagated the
    secret material onto the wire would leak HMAC secrets to every
    list response — catastrophic.

    The base contract (no `secret` field on the projection) is
    pre-existing; this test extends it to the new rotation columns
    so a refactor that adds them by mistake fails here loudly.
    """
    future = datetime.now(UTC) + timedelta(hours=14)
    out = WebhookSubscriptionOut.model_validate(_orm_like(secret_previous="should-never-appear", expires_at=future))
    dumped = out.model_dump(mode="json")
    # The three columns that carry secret material:
    for forbidden in ("secret", "secret_previous", "secret_previous_expires_at"):
        assert forbidden not in dumped, (
            f"WebhookSubscriptionOut.model_dump() leaked {forbidden!r} — "
            "the rotation projection must surface only the derived "
            "(active, remaining) fields, never the raw columns."
        )
    # And the synthesised fields ARE present:
    assert dumped["secret_previous_active"] is True
    assert dumped["secret_previous_grace_seconds_remaining"] > 0


def test_model_validate_from_dict_input():
    """The schema is also called against dict inputs (existing
    test_sandbox.py + test_webhooks_router.py go this route). Pin
    the dict path so a refactor that special-cases the ORM branch
    only doesn't silently drop the projection for dict callers."""
    future = datetime.now(UTC) + timedelta(hours=2)
    payload = {
        "id": uuid4(),
        "url": "https://example.com/hook",
        "event_types": [],
        "enabled": True,
        "last_delivery_at": None,
        "failure_count": 0,
        "created_at": datetime.now(UTC),
        "secret_previous": "x" * 64,
        "secret_previous_expires_at": future,
    }
    out = WebhookSubscriptionOut.model_validate(payload)
    assert out.secret_previous_active is True
    assert out.secret_previous_grace_seconds_remaining > 0
