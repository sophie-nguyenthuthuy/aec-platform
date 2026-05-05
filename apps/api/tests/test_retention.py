"""Tests for retention + archival.

Pure-function + fake-session level — no real Postgres. The cron's
DELETE-with-CTE shape is exercised at the SQL-pin layer (we assert
the bound query has `INTERVAL` + `LIMIT :cap`); a real DELETE is
covered by integration tests against the platform's RLS suite.

S3 archive is mocked at the boto3 client level so we can verify the
JSONL body shape + bucket key without standing up moto.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from services.retention import (
    RETENTION_POLICIES,
    collect_stats,
    policy_ttl_days,
    prune_table,
    run_retention_cron,
)

pytestmark = pytest.mark.asyncio


# ---------- Fake session ----------


class FakeAsyncSession:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, dict[str, Any]]] = []
        self._results: list[Any] = []
        self.committed = 0
        self.rolled_back = 0

    def push(self, result: Any) -> None:
        self._results.append(result)

    async def commit(self) -> None:
        self.committed += 1

    async def rollback(self) -> None:
        self.rolled_back += 1

    async def close(self) -> None: ...

    async def execute(self, stmt: Any, params: dict[str, Any] | None = None) -> Any:
        self.calls.append((stmt, params or {}))
        if self._results:
            return self._results.pop(0)
        r = MagicMock()
        r.mappings.return_value.all.return_value = []
        r.mappings.return_value.one.return_value = {
            "row_count": 0,
            "oldest_at": None,
            "overdue_count": 0,
        }
        return r


# ---------- TTL config ----------


async def test_policy_ttl_uses_default_when_no_override(monkeypatch):
    """Without an env override, the policy's hardcoded default
    applies. Pin the audit-events default at 365 — the compliance
    floor we promised customers."""
    audit = next(p for p in RETENTION_POLICIES if p.table == "audit_events")
    assert audit.default_days == 365
    assert policy_ttl_days(audit) == 365


async def test_policy_ttl_reads_env_override(monkeypatch):
    """`AEC_RETENTION_AUDIT_EVENTS_DAYS=730` extends audit retention
    for compliance-conscious tenants. Round-trip through `Settings`."""
    from core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("AEC_RETENTION_AUDIT_EVENTS_DAYS", "730")
    audit = next(p for p in RETENTION_POLICIES if p.table == "audit_events")
    assert policy_ttl_days(audit) == 730
    get_settings.cache_clear()


async def test_policy_ttl_ignores_negative_or_zero_override(monkeypatch):
    """A misconfig (`AEC_RETENTION_…_DAYS=0`) must NOT collapse the
    TTL to "delete everything immediately" — fall back to the default."""
    from core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("AEC_RETENTION_SEARCH_QUERIES_DAYS", "0")
    sq = next(p for p in RETENTION_POLICIES if p.table == "search_queries")
    assert policy_ttl_days(sq) == sq.default_days
    get_settings.cache_clear()


# ---------- collect_stats ----------


async def test_collect_stats_returns_one_row_per_policy():
    """Pin the response shape so the admin dashboard contract stays
    stable. One entry per registry policy, in policy order."""
    fake = FakeAsyncSession()
    # Make every table return the same totals so we can compare easily.
    for _ in RETENTION_POLICIES:
        r = MagicMock()
        r.mappings.return_value.one.return_value = {
            "row_count": 1234,
            "oldest_at": datetime(2026, 1, 1, tzinfo=UTC),
            "overdue_count": 50,
        }
        fake.push(r)

    stats = await collect_stats(fake)
    assert len(stats) == len(RETENTION_POLICIES)
    assert [s["table"] for s in stats] == [p.table for p in RETENTION_POLICIES]
    audit = next(s for s in stats if s["table"] == "audit_events")
    assert audit["row_count"] == 1234
    assert audit["overdue_count"] == 50
    assert audit["projected_next_prune_count"] == 50
    assert audit["archived_to_s3"] is True


async def test_collect_stats_caps_projected_count():
    """A 1M-row backlog is reported as the per-run cap, not the raw
    overdue count — operationally what matters."""
    fake = FakeAsyncSession()
    for _ in RETENTION_POLICIES:
        r = MagicMock()
        r.mappings.return_value.one.return_value = {
            "row_count": 1_000_000,
            "oldest_at": datetime(2020, 1, 1, tzinfo=UTC),
            "overdue_count": 1_000_000,
        }
        fake.push(r)
    stats = await collect_stats(fake)
    assert all(s["projected_next_prune_count"] == 10_000 for s in stats)


# ---------- prune_table ----------


async def test_prune_table_uses_capped_delete_with_returning():
    """SQL shape pin: must use `WITH victims AS (... LIMIT :cap)` +
    DELETE … RETURNING. Otherwise the cron would either lock the
    table for too long or skip the archive path."""
    fake = FakeAsyncSession()
    # Empty result set — exercise the shape, not the archive.
    r = MagicMock()
    r.mappings.return_value.all.return_value = []
    fake.push(r)

    audit = next(p for p in RETENTION_POLICIES if p.table == "audit_events")
    out = await prune_table(fake, policy=audit)
    assert out == {"table": "audit_events", "deleted_count": 0, "archive_key": None}

    sql = str(fake.calls[0][0])
    assert "WITH victims" in sql
    assert "LIMIT :cap" in sql
    assert "RETURNING" in sql
    # Bound cap must match the per-run hard limit.
    assert fake.calls[0][1]["cap"] == 10_000


async def test_prune_table_honours_extra_where():
    """webhook_deliveries policy excludes pending rows via extra_where —
    pin the fragment lands in the SQL so the cron can never delete a
    delivery that's still queued for retry."""
    fake = FakeAsyncSession()
    r = MagicMock()
    r.mappings.return_value.all.return_value = []
    fake.push(r)

    wh = next(p for p in RETENTION_POLICIES if p.table == "webhook_deliveries")
    await prune_table(fake, policy=wh)
    sql = str(fake.calls[0][0])
    assert "status IN ('delivered', 'failed')" in sql


async def test_prune_table_archives_to_s3_when_enabled(monkeypatch):
    """archive=True policy: rows go to S3 as JSONL before delete.
    We mock the boto3 client at the aioboto3.Session.client layer so
    the call shape is verified without real network."""
    fake = FakeAsyncSession()
    deleted_rows = [{"id": uuid4(), "action": "x", "created_at": datetime(2025, 1, 1, tzinfo=UTC)}]
    r = MagicMock()
    r.mappings.return_value.all.return_value = deleted_rows
    fake.push(r)

    captured: dict[str, Any] = {}

    class FakeS3Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def put_object(self, **kw):
            captured.update(kw)
            return {}

    class FakeAioSession:
        def __init__(self, region_name=None):
            pass

        def client(self, name):
            return FakeS3Client()

    monkeypatch.setattr(
        "services.retention.get_settings",
        lambda: type("S", (), {"s3_bucket": "test-bucket", "aws_region": "ap-southeast-1"})(),
    )
    # Patch aioboto3 inside the lazy import.
    import sys
    import types

    fake_aioboto3 = types.ModuleType("aioboto3")
    fake_aioboto3.Session = FakeAioSession  # type: ignore[attr-defined]
    sys.modules["aioboto3"] = fake_aioboto3

    audit = next(p for p in RETENTION_POLICIES if p.table == "audit_events")
    out = await prune_table(fake, policy=audit)
    assert out["deleted_count"] == 1
    assert out["archive_key"] is not None
    assert out["archive_key"].startswith("retention/audit_events/")
    # JSONL body shape.
    assert captured["Bucket"] == "test-bucket"
    assert captured["ContentType"] == "application/x-ndjson"
    body = captured["Body"].decode("utf-8")
    assert body.count("\n") == 0  # one row → one line, no trailing newline
    # UUID + datetime survive serialisation via default=str.
    import json

    parsed = json.loads(body)
    assert parsed["action"] == "x"


async def test_prune_table_skips_archive_when_no_bucket_configured(monkeypatch, caplog):
    """No S3 bucket → log a warning, delete proceeds. Don't gate the
    delete on archive availability — that would let a missing bucket
    block storage cleanup forever."""
    fake = FakeAsyncSession()
    r = MagicMock()
    r.mappings.return_value.all.return_value = [{"id": uuid4()}]
    fake.push(r)

    monkeypatch.setattr(
        "services.retention.get_settings",
        lambda: type("S", (), {"s3_bucket": "", "aws_region": "ap-southeast-1"})(),
    )

    audit = next(p for p in RETENTION_POLICIES if p.table == "audit_events")
    out = await prune_table(fake, policy=audit)
    assert out["deleted_count"] == 1
    assert out["archive_key"] is None


# ---------- run_retention_cron ----------


async def test_run_retention_cron_iterates_all_policies_and_commits_per_table():
    """Per-table commit so a partial failure leaves earlier tables
    pruned. Pin commit count == policy count when all succeed."""
    fake = FakeAsyncSession()
    # One result per policy, all empty.
    for _ in RETENTION_POLICIES:
        r = MagicMock()
        r.mappings.return_value.all.return_value = []
        fake.push(r)

    summaries = await run_retention_cron(fake)
    assert len(summaries) == len(RETENTION_POLICIES)
    assert all(s["deleted_count"] == 0 for s in summaries)
    # One commit per table.
    assert fake.committed == len(RETENTION_POLICIES)
    assert fake.rolled_back == 0


async def test_run_retention_cron_isolates_per_table_failures():
    """A DB error on one table must NOT skip the others. Pin: failed
    table emits an `error` field but the cron still runs the rest."""
    fake = FakeAsyncSession()
    # First call: explode. Subsequent: empty.
    boom = MagicMock()
    boom.mappings.side_effect = RuntimeError("table busy")
    fake.push(boom)
    for _ in range(len(RETENTION_POLICIES) - 1):
        r = MagicMock()
        r.mappings.return_value.all.return_value = []
        fake.push(r)

    summaries = await run_retention_cron(fake)
    assert len(summaries) == len(RETENTION_POLICIES)
    assert "error" in summaries[0]
    # The other tables ran cleanly.
    assert all("error" not in s for s in summaries[1:])
    assert fake.rolled_back == 1
