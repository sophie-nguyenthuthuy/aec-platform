"""Per-tenant retention overrides (cycle T3).

Pinned seams:
  1. `policy_ttl_days(policy, per_tenant_override=N)` — N takes
     precedence over env / default. The cron passes the override
     in; the helper threads it.
  2. `set_retention_override` rejects unknown table names + values
     shorter than the policy default (extend-only).
  3. UPSERT on (organization_id, table_name) — re-setting the same
     row updates rather than creating a duplicate.
  4. Router endpoints are admin-gated.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
from uuid import UUID

import pytest


pytestmark = pytest.mark.asyncio


ORG_ID = UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")
USER_ID = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")


class _FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._results: list[Any] = []

    def push(self, result: Any) -> None:
        self._results.append(result)

    async def execute(self, stmt: Any, params: dict[str, Any] | None = None) -> Any:
        sql_text = stmt.text if hasattr(stmt, "text") else str(stmt)
        self.calls.append((sql_text, params or {}))
        if self._results:
            return self._results.pop(0)
        r = MagicMock()
        r.rowcount = 0
        r.mappings.return_value.first.return_value = None
        r.mappings.return_value.all.return_value = []
        return r

    async def commit(self) -> None: ...
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None


# ---------- policy_ttl_days precedence ----------


def test_policy_ttl_days_per_tenant_override_takes_precedence():
    """Per-tenant override > env > policy default. Pin so a refactor
    that flips the precedence (env first) silently reverts a
    compliance customer's 7y to the env default."""
    from services.retention import RETENTION_POLICIES, policy_ttl_days

    audit_policy = next(p for p in RETENTION_POLICIES if p.table == "audit_events")
    # Per-tenant override of 2555d (7 years) — wins over env/default.
    assert policy_ttl_days(audit_policy, per_tenant_override=2555) == 2555


def test_policy_ttl_days_falls_back_to_default_when_no_override():
    """No per-tenant override + no env override → policy default
    (back-compat behaviour)."""
    from services.retention import RETENTION_POLICIES, policy_ttl_days

    audit_policy = next(p for p in RETENTION_POLICIES if p.table == "audit_events")
    assert policy_ttl_days(audit_policy) == audit_policy.default_days


def test_policy_ttl_days_ignores_zero_or_negative_override():
    """A zero/negative override means "no override" — falls through
    to the next layer. Pin the defensive fallback."""
    from services.retention import RETENTION_POLICIES, policy_ttl_days

    audit_policy = next(p for p in RETENTION_POLICIES if p.table == "audit_events")
    assert policy_ttl_days(audit_policy, per_tenant_override=0) == audit_policy.default_days
    assert policy_ttl_days(audit_policy, per_tenant_override=-100) == audit_policy.default_days


# ---------- set_retention_override validation ----------


async def test_set_override_rejects_unknown_table():
    """Unknown table_name → ValueError. Pin so a typo in the admin
    UI's PUT body fails fast rather than landing a row the cron
    can never use."""
    from services.retention import set_retention_override

    session = _FakeSession()
    with pytest.raises(ValueError, match="unknown table_name"):
        await set_retention_override(
            session,
            organization_id=ORG_ID,
            table_name="not_a_real_table",
            ttl_days=365,
            set_by=USER_ID,
            reason=None,
        )
    # Critical: the validation MUST run before any DB write.
    assert session.calls == []


async def test_set_override_rejects_shorter_than_default():
    """Per-tenant overrides may EXTEND retention (compliance
    commitment), never shorten. A shorter ttl_days raises so
    governance defaults aren't silently undone per-tenant."""
    from services.retention import set_retention_override

    session = _FakeSession()
    # audit_events default is 365d; try to set 30d.
    with pytest.raises(ValueError, match="shorter than the policy default"):
        await set_retention_override(
            session,
            organization_id=ORG_ID,
            table_name="audit_events",
            ttl_days=30,
            set_by=USER_ID,
            reason=None,
        )
    assert session.calls == []


async def test_set_override_accepts_extend():
    """Extending audit_events from 365d → 2555d (7y) is the
    canonical compliance use-case — must succeed + emit an UPSERT."""
    from services.retention import set_retention_override

    session = _FakeSession()
    out = await set_retention_override(
        session,
        organization_id=ORG_ID,
        table_name="audit_events",
        ttl_days=2555,
        set_by=USER_ID,
        reason="ISO 27001 audit retention",
    )
    assert out["ttl_days"] == 2555
    assert out["reason"] == "ISO 27001 audit retention"
    # The SQL must be an UPSERT — pin the ON CONFLICT clause so a
    # refactor that drops it silently creates duplicates per
    # re-set (PK constraint would catch it but the error message
    # would be opaque to the admin).
    sql, params = session.calls[0]
    assert "ON CONFLICT (organization_id, table_name)" in sql
    assert params["org"] == str(ORG_ID)
    assert params["table"] == "audit_events"
    assert params["ttl"] == 2555


# ---------- get/list/clear helpers ----------


async def test_get_override_returns_none_when_missing():
    """No row → None (cron's per-policy loop falls back to env /
    default). Pin so a refactor that returns 0 instead of None
    breaks the back-compat path silently."""
    from services.retention import get_retention_override

    session = _FakeSession()
    r = MagicMock()
    r.mappings.return_value.first.return_value = None
    session.push(r)

    out = await get_retention_override(session, organization_id=ORG_ID, table_name="audit_events")
    assert out is None


async def test_get_override_returns_int_when_present():
    from services.retention import get_retention_override

    session = _FakeSession()
    r = MagicMock()
    r.mappings.return_value.first.return_value = {"ttl_days": 2555}
    session.push(r)

    out = await get_retention_override(session, organization_id=ORG_ID, table_name="audit_events")
    assert out == 2555


async def test_clear_override_returns_true_on_delete():
    from services.retention import clear_retention_override

    session = _FakeSession()
    r = MagicMock()
    r.rowcount = 1
    session.push(r)

    out = await clear_retention_override(session, organization_id=ORG_ID, table_name="audit_events")
    assert out is True


async def test_clear_override_returns_false_when_no_row():
    """Idempotent on the no-row path — admin can double-click
    "Clear" without seeing an error."""
    from services.retention import clear_retention_override

    session = _FakeSession()
    r = MagicMock()
    r.rowcount = 0
    session.push(r)

    out = await clear_retention_override(session, organization_id=ORG_ID, table_name="audit_events")
    assert out is False
