"""Audit log CSV export (cycle P3).

Three seams pinned here:

  1. **413 above the cap.** A 6-month export on a busy org returns a
     loud 413 BEFORE the heavy SELECT runs, with a hint to tighten
     the date range. Silently truncating would mislead a compliance
     reviewer who reads the CSV as authoritative — pin the failure
     mode.

  2. **Header set + column order.** `_CSV_COLUMNS` pins the exact
     header line; downstream pipelines (jq, pandas, Excel) key off
     the header names. A refactor that reorders / renames a column
     fails this test loudly.

  3. **Row dict shape.** Per-row, the synthesised columns
     (`_actor_kind`, `_before_json`, `_after_json`) must produce the
     vocabulary the API filter accepts (`user|api_key|system`) and
     valid JSON respectively. Pin both so a pipeline that
     re-imports the CSV via pandas + json.loads doesn't break on a
     subset of rows.

The router test mounts only the audit router with a stubbed
FakeAsyncSession that returns canned `count` and rows. We don't drive
a real Postgres here — the SQL is exercised by the live pipeline; the
shape of what the endpoint emits is what we pin.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from middleware.auth import AuthContext, require_auth

pytestmark = pytest.mark.asyncio


ORG_ID = UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")
USER_ID = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")


class _FakeSession:
    """Minimal session stub — pushes scalar_one results for the
    count() query, then mappings().all() for the SELECT."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, dict[str, Any]]] = []
        self._results: list[Any] = []

    def push(self, result: Any) -> None:
        self._results.append(result)

    async def commit(self) -> None: ...
    async def close(self) -> None: ...

    async def execute(self, stmt: Any, params: dict[str, Any] | None = None) -> Any:
        self.calls.append((stmt, params or {}))
        if self._results:
            return self._results.pop(0)
        r = MagicMock()
        r.scalar_one.return_value = 0
        r.mappings.return_value.all.return_value = []
        return r


def _scalar(value: Any) -> Any:
    """Helper: build a result whose `.scalar_one()` returns `value`."""
    r = MagicMock()
    r.scalar_one.return_value = value
    return r


def _mappings(rows: list[dict[str, Any]]) -> Any:
    """Helper: build a result whose `.mappings().all()` returns rows."""
    r = MagicMock()
    r.mappings.return_value.all.return_value = rows
    return r


def _build_app(fake_db: _FakeSession, role: str = "admin") -> FastAPI:
    """Mount the audit router with auth + db stubs. Same pattern as
    test_audit_router.py for consistency."""
    from db.deps import get_db
    from routers import audit as audit_router

    app = FastAPI()
    app.include_router(audit_router.router)

    auth_ctx = AuthContext(
        user_id=USER_ID,
        organization_id=ORG_ID,
        role=role,
        email="ops@example.com",
    )

    async def _db_override() -> AsyncIterator[_FakeSession]:
        yield fake_db

    app.dependency_overrides[require_auth] = lambda: auth_ctx
    app.dependency_overrides[get_db] = _db_override
    return app


# ---------- 413 above the cap --------------------------------------


async def test_csv_export_413s_when_total_exceeds_cap():
    """A 6-month query returning 60k rows should 413 before the heavy
    SELECT runs. Pin the response code AND the hint text — a
    compliance reviewer reading the message should know to tighten
    the range, not refresh and try again."""
    from routers.audit import _CSV_MAX_ROWS

    db = _FakeSession()
    # First execute() is the count() — return 60k.
    db.push(_scalar(_CSV_MAX_ROWS + 10_000))

    app = _build_app(db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/audit/events.csv")

    assert res.status_code == 413, res.text
    body = res.json()
    # The detail must mention the cap so the reviewer knows what to
    # do. Pin substring presence so a refactor that drops the hint
    # surfaces.
    detail = body.get("detail", body)
    assert "Tighten" in str(detail) or "tighten" in str(detail), (
        f"413 message should include a tightening hint; got {detail!r}"
    )

    # Critically: only ONE execute() call should have happened (the
    # count). Pin so a regression that runs the SELECT first and
    # only checks the count after wastes the DB round-trip.
    assert len(db.calls) == 1


# ---------- Header set + row stream --------------------------------


async def test_csv_export_emits_pinned_header_set():
    """`_CSV_COLUMNS` is the contract with downstream pipelines — pin
    the exact set + order so a refactor that reorders columns
    surfaces visibly."""
    from routers.audit import _CSV_COLUMNS

    expected_headers = [
        "when",
        "action",
        "resource_type",
        "resource_id",
        "actor_email",
        "actor_api_key_name",
        "actor_kind",
        "ip",
        "user_agent",
        "before",
        "after",
    ]
    actual_headers = [h for h, _src in _CSV_COLUMNS]
    assert actual_headers == expected_headers, (
        f"CSV column header set drifted: expected {expected_headers}, got {actual_headers}. "
        "Downstream pipelines key off this exact set."
    )


async def test_csv_export_streams_a_row_per_audit_event():
    """End-to-end: count returns a small number, rows return canned
    audit events, the response body is parseable as a CSV with
    header + one row per event."""
    db = _FakeSession()
    db.push(_scalar(2))  # count
    db.push(
        _mappings(
            [
                {
                    "id": uuid4(),
                    "organization_id": ORG_ID,
                    "actor_user_id": USER_ID,
                    "actor_api_key_id": None,
                    "actor_email": "alice@example.com",
                    "actor_api_key_name": None,
                    "action": "org.member.role_change",
                    "resource_type": "org_members",
                    "resource_id": uuid4(),
                    "before": {"role": "member"},
                    "after": {"role": "admin"},
                    "ip": "203.0.113.7",
                    "user_agent": "Mozilla/5.0",
                    "created_at": datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
                },
                {
                    "id": uuid4(),
                    "organization_id": ORG_ID,
                    "actor_user_id": None,
                    "actor_api_key_id": None,  # system actor
                    "actor_email": None,
                    "actor_api_key_name": None,
                    "action": "costpulse.rfq.slots_expired",
                    "resource_type": "rfq",
                    "resource_id": uuid4(),
                    "before": {"status": "sent"},
                    "after": {"status": "expired"},
                    "ip": None,
                    "user_agent": None,
                    "created_at": datetime(2026, 5, 1, 13, 0, tzinfo=UTC),
                },
            ]
        )
    )

    app = _build_app(db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/audit/events.csv?since_days=7")

    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("text/csv"), res.headers
    # Content-Disposition: attachment so browsers save instead of
    # rendering. Pin the marker so a refactor that drops it doesn't
    # surface as "browser opens CSV inline" UX regression.
    assert "attachment" in res.headers.get("content-disposition", ""), res.headers
    assert "no-store" in res.headers.get("cache-control", ""), res.headers

    lines = res.text.strip().split("\n")
    assert len(lines) == 3, f"expected header + 2 rows, got {len(lines)} lines"
    # Header line — exact prefix.
    assert lines[0].startswith("when,action,resource_type,"), lines[0]


async def test_csv_export_synthesises_actor_kind_per_row():
    """The `actor_kind` column is computed in Python from the
    presence of `actor_user_id` / `actor_api_key_id`. Pin all three
    branches: `user`, `api_key`, `system`."""
    db = _FakeSession()
    db.push(_scalar(3))
    db.push(
        _mappings(
            [
                # user actor
                {
                    "id": uuid4(),
                    "organization_id": ORG_ID,
                    "actor_user_id": USER_ID,
                    "actor_api_key_id": None,
                    "actor_email": "u@e.com",
                    "actor_api_key_name": None,
                    "action": "x",
                    "resource_type": "y",
                    "resource_id": None,
                    "before": {},
                    "after": {},
                    "ip": None,
                    "user_agent": None,
                    "created_at": datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
                },
                # api_key actor
                {
                    "id": uuid4(),
                    "organization_id": ORG_ID,
                    "actor_user_id": None,
                    "actor_api_key_id": uuid4(),
                    "actor_email": None,
                    "actor_api_key_name": "my-key",
                    "action": "x",
                    "resource_type": "y",
                    "resource_id": None,
                    "before": {},
                    "after": {},
                    "ip": None,
                    "user_agent": None,
                    "created_at": datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
                },
                # system actor (both null)
                {
                    "id": uuid4(),
                    "organization_id": ORG_ID,
                    "actor_user_id": None,
                    "actor_api_key_id": None,
                    "actor_email": None,
                    "actor_api_key_name": None,
                    "action": "x",
                    "resource_type": "y",
                    "resource_id": None,
                    "before": {},
                    "after": {},
                    "ip": None,
                    "user_agent": None,
                    "created_at": datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
                },
            ]
        )
    )

    app = _build_app(db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/audit/events.csv")

    import csv as _csv
    import io as _io

    reader = _csv.DictReader(_io.StringIO(res.text))
    rows = list(reader)
    assert len(rows) == 3
    actor_kinds = [r["actor_kind"] for r in rows]
    assert actor_kinds == ["user", "api_key", "system"], f"actor_kind synthesis drifted; got {actor_kinds}"


async def test_csv_export_before_after_columns_are_valid_json():
    """The `before` / `after` cells carry the full JSON diff. A
    pipeline doing `json.loads(row['before'])` must succeed. Pin so
    a refactor that emits a Python repr (e.g. via `str(dict)`)
    breaks here, not at the reviewer's pandas import."""
    db = _FakeSession()
    db.push(_scalar(1))
    db.push(
        _mappings(
            [
                {
                    "id": uuid4(),
                    "organization_id": ORG_ID,
                    "actor_user_id": USER_ID,
                    "actor_api_key_id": None,
                    "actor_email": "u@e.com",
                    "actor_api_key_name": None,
                    "action": "test",
                    "resource_type": "x",
                    "resource_id": None,
                    "before": {"role": "member", "ts": datetime(2026, 5, 1, tzinfo=UTC)},
                    "after": {"role": "admin", "list": [1, 2, 3]},
                    "ip": None,
                    "user_agent": None,
                    "created_at": datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
                }
            ]
        )
    )

    app = _build_app(db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/audit/events.csv")

    import csv as _csv
    import io as _io

    reader = _csv.DictReader(_io.StringIO(res.text))
    row = next(reader)
    # Must round-trip through json.loads.
    before = json.loads(row["before"])
    after = json.loads(row["after"])
    assert before == {"role": "member", "ts": "2026-05-01 00:00:00+00:00"}
    assert after == {"role": "admin", "list": [1, 2, 3]}


# ---------- Cap constant -------------------------------------------


def test_csv_max_rows_is_50k():
    """50k matches the retention prune cap idiom and keeps the
    streaming response under ~30MB. A "let's bump to 500k" PR should
    be a deliberate code-review decision — pin so the change requires
    touching this test in the same commit."""
    from routers.audit import _CSV_MAX_ROWS

    assert _CSV_MAX_ROWS == 50_000, (
        f"_CSV_MAX_ROWS drifted from 50k (current: {_CSV_MAX_ROWS}). "
        "Bumping the cap means the streaming response can grow past "
        "30MB; review request budget + memory trade-off in audit.py "
        "before changing."
    )


# ---------- Member / viewer gating ---------------------------------


async def test_csv_export_403s_for_member():
    """Same RBAC as the JSON list endpoint — Role.ADMIN required.
    Pin so a refactor that drops `require_min_role(Role.ADMIN)`
    surfaces here. The audit log can leak who-did-what across teams
    and must stay admin-gated regardless of which endpoint accesses
    it."""
    db = _FakeSession()
    app = _build_app(db, role="member")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/audit/events.csv")

    assert res.status_code == 403, res.text
