"""Unit tests for the dedicated codeguard quota router module.

`routers/codeguard_quota.py` carries `/quota/audit` and `/quota/top-users`,
plus their cursor-parsing, action-enum, and limit-clamping logic. The
parent codeguard router tests it transitively via the snapshot
(presence) + the stub-detection (body issues SQL); these tests pin the
SPECIFIC contracts the handlers enforce so a refactor that, say,
silently widens the action enum or stops clamping the limit surfaces
loudly here.

Tier 1 — every test stubs the AsyncSession via `_RowStub` / AsyncMock,
so no live Postgres needed. The SQL semantics themselves (cursor
ordering, FULL OUTER JOIN behavior) are validated in Tier 3
integration tests.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

pytestmark = pytest.mark.asyncio


class _RowStub:
    """Mimics SQLAlchemy `Row` — attribute access on bound columns."""

    def __init__(self, **fields):
        for k, v in fields.items():
            setattr(self, k, v)


def _stub_db(rows: list[_RowStub] | None = None):
    """Build a MagicMock db whose execute() returns `rows`. Captures
    the SQL + bound params on every call for inspection."""
    captured: list[tuple[str, dict]] = []

    async def _execute(stmt, params=None, *args, **kwargs):
        sql_str = getattr(stmt, "text", None) or str(stmt)
        captured.append((sql_str, params or {}))
        result = MagicMock()
        result.all.return_value = rows or []
        return result

    db = MagicMock()
    db.execute = AsyncMock(side_effect=_execute)
    db._captured = captured  # type: ignore[attr-defined]
    return db


def _stub_auth():
    auth = MagicMock()
    auth.organization_id = uuid4()
    auth.user_id = uuid4()
    return auth


# ---------- /quota/audit -------------------------------------------------


async def test_audit_clamps_oversized_limit_to_200():
    """`limit=999` should be clamped to 200 server-side. Without the
    clamp, a misbehaving client could request a 100k-row page and
    blow up the response. Pin via the bound param the SQL sees."""
    from routers.codeguard_quota import get_codeguard_quota_audit

    db = _stub_db([])
    auth = _stub_auth()

    await get_codeguard_quota_audit(auth=auth, db=db, limit=999)
    sql, params = db._captured[-1]
    assert params["limit"] == 200, (
        f"Expected limit clamped to 200, got {params['limit']}. "
        "An unbounded limit lets one client overwhelm the response stream."
    )


async def test_audit_clamps_zero_limit_to_one():
    """`limit=0` (or negative) should clamp UP to 1. A `LIMIT 0` would
    return an empty result that the UI would interpret as "end of
    log" — confusing for an admin who clearly has audit entries."""
    from routers.codeguard_quota import get_codeguard_quota_audit

    db = _stub_db([])
    auth = _stub_auth()

    await get_codeguard_quota_audit(auth=auth, db=db, limit=0)
    _, params = db._captured[-1]
    assert params["limit"] == 1


async def test_audit_rejects_unknown_action_with_400():
    """Closed action vocabulary — `quota_archive` (hypothetical
    future) returns 400 with a list of allowed values, not a silent
    pass-through that returns empty results."""
    from routers.codeguard_quota import get_codeguard_quota_audit

    db = _stub_db([])
    auth = _stub_auth()

    with pytest.raises(HTTPException) as exc:
        await get_codeguard_quota_audit(auth=auth, db=db, action="quota_archive")
    assert exc.value.status_code == 400
    # Error message lists the allowed values so the operator knows what
    # to try — pin a sample so a refactor that drops the list gets caught.
    assert "quota_set" in exc.value.detail
    assert "quota_reconcile" in exc.value.detail


async def test_audit_accepts_quota_reconcile_action():
    """`quota_reconcile` is the action emitted by the reconcile cron's
    remediation path. The audit page MUST be able to filter to it —
    otherwise the surface that exists to investigate cap-cache
    realignments is broken."""
    from routers.codeguard_quota import get_codeguard_quota_audit

    db = _stub_db([])
    auth = _stub_auth()

    # Should NOT raise.
    await get_codeguard_quota_audit(auth=auth, db=db, action="quota_reconcile")
    _, params = db._captured[-1]
    assert params["action"] == "quota_reconcile"


async def test_audit_rejects_malformed_cursor_with_400():
    """Cursor format is `<iso_ts>:<uuid>`. A cursor without a colon
    is a client bug; surface it as 400 not as a silent empty page."""
    from routers.codeguard_quota import get_codeguard_quota_audit

    db = _stub_db([])
    auth = _stub_auth()

    with pytest.raises(HTTPException) as exc:
        await get_codeguard_quota_audit(auth=auth, db=db, before="malformed-no-colon")
    assert exc.value.status_code == 400


async def test_audit_well_formed_cursor_binds_split_params():
    """A `<iso_ts>:<uuid>` cursor splits on the RIGHTMOST `:` (since
    ISO timestamps contain colons in `HH:MM:SS`). Pin the split via
    the bound params."""
    from routers.codeguard_quota import get_codeguard_quota_audit

    db = _stub_db([])
    auth = _stub_auth()

    cursor_ts = "2026-05-01T12:34:56+00:00"
    cursor_id = "00000000-0000-0000-0000-000000000001"
    await get_codeguard_quota_audit(auth=auth, db=db, before=f"{cursor_ts}:{cursor_id}")
    _, params = db._captured[-1]
    assert params["cursor_ts"] == cursor_ts
    assert params["cursor_id"] == cursor_id


async def test_audit_returns_next_cursor_only_when_page_full():
    """`next_cursor` is non-null ONLY when the response returned
    exactly `limit` rows (signal: "there might be more"). A short
    page returns null so the UI knows to stop fetching. Pin both
    branches."""
    from routers.codeguard_quota import get_codeguard_quota_audit

    auth = _stub_auth()
    # Limit 3, return 3 rows → next_cursor present.
    full_rows = [
        _RowStub(
            id=UUID(f"00000000-0000-0000-0000-00000000000{i}"),
            occurred_at=MagicMock(isoformat=lambda i=i: f"2026-05-0{i}T00:00:00"),
            actor="bob",
            action="quota_set",
            before=None,
            after=None,
        )
        for i in (1, 2, 3)
    ]
    db = _stub_db(full_rows)
    payload_full = await get_codeguard_quota_audit(auth=auth, db=db, limit=3)
    assert payload_full["data"]["next_cursor"] is not None

    # Limit 3, return 2 rows → next_cursor None (end of log).
    db_short = _stub_db(full_rows[:2])
    payload_short = await get_codeguard_quota_audit(auth=auth, db=db_short, limit=3)
    assert payload_short["data"]["next_cursor"] is None


# ---------- /quota/top-users ---------------------------------------------


async def test_top_users_clamps_limit_to_50():
    """Server-clamps to 1..50 — UI defaults to 10. A request for 999
    must come back at 50 to bound the response."""
    from routers.codeguard_quota import get_codeguard_quota_top_users

    db = _stub_db([])
    auth = _stub_auth()

    await get_codeguard_quota_top_users(auth=auth, db=db, limit=999)
    _, params = db._captured[-1]
    assert params["limit"] == 50


async def test_top_users_returns_empty_array_when_no_usage():
    """Fresh org with no usage rows → `users: []`, NOT a missing
    field. The UI's "no data" empty state hinges on this contract."""
    from routers.codeguard_quota import get_codeguard_quota_top_users

    db = _stub_db([])
    auth = _stub_auth()

    payload = await get_codeguard_quota_top_users(auth=auth, db=db)
    assert payload["data"]["users"] == []
    assert payload["data"]["breakdown"] is False


async def test_top_users_breakdown_false_skips_breakdown_query():
    """`breakdown=false` (default) → exactly 1 SQL execute (the
    top-users SELECT). The breakdown query should NOT fire — that
    extra round-trip is what the flag exists to gate."""
    from routers.codeguard_quota import get_codeguard_quota_top_users

    db = _stub_db([])
    auth = _stub_auth()

    await get_codeguard_quota_top_users(auth=auth, db=db, breakdown=False)
    assert db.execute.call_count == 1


async def test_top_users_breakdown_true_issues_two_queries(monkeypatch):
    """`breakdown=true` → 2 SQL executes: the top-users SELECT plus
    the per-route breakdown lookup. Pin the count so a refactor
    that accidentally fires N+1 queries (one per user) is caught."""
    from routers.codeguard_quota import get_codeguard_quota_top_users

    user_id = uuid4()
    user_row = _RowStub(
        user_id=user_id,
        email="alice@example.com",
        input_tokens=1000,
        output_tokens=200,
        total_tokens=1200,
    )
    breakdown_row = _RowStub(
        user_id=user_id,
        route_key="scan",
        input_tokens=800,
        output_tokens=160,
    )
    captured: list = []

    async def _execute(stmt, params=None, *args, **kwargs):
        captured.append(stmt)
        result = MagicMock()
        # First execute: top-users SELECT → return the user.
        # Second execute: breakdown lookup → return the breakdown row.
        if len(captured) == 1:
            result.all.return_value = [user_row]
        else:
            result.all.return_value = [breakdown_row]
        return result

    db = MagicMock()
    db.execute = AsyncMock(side_effect=_execute)
    auth = _stub_auth()

    payload = await get_codeguard_quota_top_users(auth=auth, db=db, breakdown=True)
    assert db.execute.call_count == 2
    # The breakdown SQL must reference the per-route table —
    # otherwise the second call is a wrong query that returns garbage.
    second_sql = getattr(captured[1], "text", str(captured[1]))
    assert "codeguard_user_usage_by_route" in second_sql

    users = payload["data"]["users"]
    assert len(users) == 1
    assert users[0]["routes"] == [
        {
            "route_key": "scan",
            "input_tokens": 800,
            "output_tokens": 160,
            "total_tokens": 960,
        }
    ]


async def test_top_users_breakdown_includes_empty_routes_for_users_without_breakdown():
    """When `breakdown=true`, every user gets a `routes` array — even
    empty if they have no breakdown rows. The UI relies on the field's
    presence (not the top-level flag) to choose the rendering branch."""
    from routers.codeguard_quota import get_codeguard_quota_top_users

    user_with_breakdown = _RowStub(
        user_id=uuid4(),
        email="alice@example.com",
        input_tokens=1000,
        output_tokens=200,
        total_tokens=1200,
    )
    user_without_breakdown = _RowStub(
        user_id=uuid4(),
        email="bob@example.com",
        input_tokens=500,
        output_tokens=100,
        total_tokens=600,
    )
    breakdown_row = _RowStub(
        user_id=user_with_breakdown.user_id,
        route_key="query",
        input_tokens=500,
        output_tokens=100,
    )
    captured: list = []

    async def _execute(stmt, params=None, *args, **kwargs):
        captured.append(stmt)
        result = MagicMock()
        if len(captured) == 1:
            result.all.return_value = [user_with_breakdown, user_without_breakdown]
        else:
            # Only the first user has breakdown rows.
            result.all.return_value = [breakdown_row]
        return result

    db = MagicMock()
    db.execute = AsyncMock(side_effect=_execute)
    auth = _stub_auth()

    payload = await get_codeguard_quota_top_users(auth=auth, db=db, breakdown=True)
    users = payload["data"]["users"]
    by_email = {u["email"]: u for u in users}
    assert by_email["alice@example.com"]["routes"] == [
        {
            "route_key": "query",
            "input_tokens": 500,
            "output_tokens": 100,
            "total_tokens": 600,
        }
    ]
    # Bob has no breakdown rows but the field MUST still be present
    # (empty list, not missing). Pin so a refactor doesn't accidentally
    # omit the field for users without breakdown data.
    assert by_email["bob@example.com"]["routes"] == []


async def test_top_users_handles_deleted_user_via_left_join():
    """A user deleted between the spend and the read (CASCADE wipes
    their user_usage row, but the user row goes first) flows through
    with `email=""`. Pin so the UI can render a "(deleted user)"
    placeholder rather than the row silently disappearing."""
    from routers.codeguard_quota import get_codeguard_quota_top_users

    db = _stub_db(
        [
            _RowStub(
                user_id=uuid4(),
                email="",  # COALESCE on NULL → ""
                input_tokens=1000,
                output_tokens=200,
                total_tokens=1200,
            )
        ]
    )
    auth = _stub_auth()

    payload = await get_codeguard_quota_top_users(auth=auth, db=db)
    assert payload["data"]["users"][0]["email"] == ""
