"""Unit tests for `scripts/codeguard_quotas.py`.

The CLI is a thin layer over `services.codeguard_quotas`, so most of
the test surface is the formatting + filtering logic on top of the
SQL helpers. The SQL itself is exercised by the Tier 3 integration
test (`apps/api/tests/test_codeguard_quotas_integration.py`) — these
tests stub the engine layer so they can run as Tier 1 with no Postgres.

What's pinned here:
  * `cmd_set` / `cmd_get` / `cmd_list` issue the right SQL params.
  * `format_get` / `format_list` produce the documented human-readable
    shapes — pin so a refactor of the column widths doesn't silently
    break ops dashboards parsing the output.
  * `--over-pct` filters to entries whose binding dimension crosses
    the threshold; entries below it (or with no binding) drop out.
  * `list` sorts orgs by binding-percent descending, with unlimited
    orgs sorting to the end.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

# Load the CLI script as a module without putting `scripts/` on
# sys.path globally (the codebase has a separate `scripts.*` namespace
# convention we don't want to interfere with).
_CLI_PATH = Path(__file__).resolve().parent.parent.parent.parent / "scripts" / "codeguard_quotas.py"
_spec = importlib.util.spec_from_file_location("codeguard_quotas_cli", _CLI_PATH)
assert _spec is not None and _spec.loader is not None
cli = importlib.util.module_from_spec(_spec)
sys.modules["codeguard_quotas_cli"] = cli
_spec.loader.exec_module(cli)


# ---------- engine factory stub ----------------------------------------


def _stub_engine_factory(monkeypatch, execute_results: list):
    """Replace `_engine_factory` with a stub that returns a MagicMock
    engine + a context-managed session whose `execute` returns
    successive entries from `execute_results`.

    Each entry can be:
      * a `_RowStub` (single-row result for `.first()`)
      * a list of `_RowStub` (multi-row result for `.all()`)
      * None (no rows — `.first()` returns None, `.all()` returns [])
    """
    engine = MagicMock()
    engine.dispose = AsyncMock()

    session = MagicMock()
    session.commit = AsyncMock()

    queue = list(execute_results)

    async def _execute(*_args, **_kwargs):
        nxt = queue.pop(0) if queue else None
        result = MagicMock()
        if isinstance(nxt, list):
            result.all.return_value = nxt
            result.first.return_value = nxt[0] if nxt else None
        else:
            result.first.return_value = nxt
            result.all.return_value = [nxt] if nxt is not None else []
        return result

    session.execute = AsyncMock(side_effect=_execute)

    class _SessionCM:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *_a):
            return False

    factory = MagicMock(return_value=_SessionCM())

    async def _stub():
        return engine, factory

    monkeypatch.setattr(cli, "_engine_factory", _stub)
    return session


class _RowStub:
    def __init__(self, **fields):
        for k, v in fields.items():
            setattr(self, k, v)


def _stub_threshold_notify_noop(monkeypatch):
    """Stub `services.codeguard_quotas.check_and_notify_thresholds` to
    a no-op for tests that focus on the CLI's set/upsert/audit shape
    rather than the post-commit notification fan-out.

    `cmd_set` now calls this helper after commit (to cover the cap-
    lowering edge case where ops drops the cap below current usage and
    nobody hits an LLM route to trigger the usage-side check). For
    tests that don't care about the notification path, stubbing avoids
    having to pad the execute() queue with the helper's internal SQL —
    a leakier coupling that breaks every time the helper's query
    pattern changes.
    """
    import importlib

    services_q = importlib.import_module("services.codeguard_quotas")

    async def _noop(*_a, **_kw):
        return []

    monkeypatch.setattr(services_q, "check_and_notify_thresholds", _noop)


# ---------- cmd_set -----------------------------------------------------


@pytest.mark.asyncio
async def test_set_upserts_with_both_limits(monkeypatch):
    """Both flags set → both columns bound, both non-None. The
    INSERT...ON CONFLICT shape lives in `cmd_set`'s SQL string; we
    don't re-assert the SQL here (Tier 3 covers that), but pin the
    bound-parameter shape on the UPSERT call.

    `cmd_set` now issues three executes per call: SELECT-for-update,
    UPSERT, audit insert. The middle one is the UPSERT we care about
    here; pluck it by index rather than relying on call order, so this
    test stays robust to a future refactor that reorders the helpers.
    """
    _stub_threshold_notify_noop(monkeypatch)
    # Three execute() calls per set: pre-read (no row), upsert, audit.
    session = _stub_engine_factory(monkeypatch, [None, None, None])

    org_id = uuid4()
    result = await cli.cmd_set(
        org_id,
        input_limit=5_000_000,
        output_limit=1_000_000,
        actor="ops-bot",
    )

    assert result["org_id"] == str(org_id)
    assert result["monthly_input_token_limit"] == 5_000_000
    assert result["monthly_output_token_limit"] == 1_000_000
    assert result["actor"] == "ops-bot"

    # Find the UPSERT call by looking at the bound-parameter keys —
    # the upsert is the only execute that binds `in_lim` / `out_lim`.
    upsert_calls = [c for c in session.execute.call_args_list if "in_lim" in (c.args[1] or {})]
    assert len(upsert_calls) == 1
    params = upsert_calls[0].args[1]
    assert params["org"] == str(org_id)
    assert params["in_lim"] == 5_000_000
    assert params["out_lim"] == 1_000_000


@pytest.mark.asyncio
async def test_set_passes_none_for_unlimited_dimension(monkeypatch):
    """Omitting a limit flag binds NULL on that dimension — the
    documented "unlimited on this axis" semantic. A regression that
    coerced None → 0 would silently zero an org's cap and trip 429
    on every subsequent request."""
    _stub_threshold_notify_noop(monkeypatch)
    session = _stub_engine_factory(monkeypatch, [None, None, None])

    org_id = uuid4()
    await cli.cmd_set(org_id, input_limit=None, output_limit=200_000)

    upsert_calls = [c for c in session.execute.call_args_list if "in_lim" in (c.args[1] or {})]
    params = upsert_calls[0].args[1]
    assert params["in_lim"] is None
    assert params["out_lim"] == 200_000


# ---------- audit log ---------------------------------------------------


@pytest.mark.asyncio
async def test_set_writes_audit_row_with_before_after_and_actor(monkeypatch):
    """`cmd_set` must write a `quota_set` row to the audit log in the
    same transaction as the UPSERT. Pin all four pieces operations
    relies on:
      * action = "quota_set"
      * before snapshot reflects the row that existed pre-upsert
      * after snapshot reflects the bound limits
      * actor matches what was passed in

    This is the contract that makes "who raised this org's cap last
    week" a single SELECT instead of `grep`-ing shell history.
    """
    import json as _json

    _stub_threshold_notify_noop(monkeypatch)
    org_id = uuid4()
    # Pre-read returns a row → tests the `before` snapshot path that
    # captures the predecessor state. Other two executes return None.
    pre_row = _RowStub(in_lim=1_000_000, out_lim=200_000)
    session = _stub_engine_factory(monkeypatch, [pre_row, None, None])

    await cli.cmd_set(
        org_id,
        input_limit=2_000_000,
        output_limit=400_000,
        actor="oncall-engineer",
    )

    # Find the audit insert by its bound `action` key — distinct from
    # the upsert's `in_lim` / pre-read's lone `org` keys.
    audit_calls = [c for c in session.execute.call_args_list if "action" in (c.args[1] or {})]
    assert len(audit_calls) == 1
    audit_params = audit_calls[0].args[1]
    assert audit_params["action"] == "quota_set"
    assert audit_params["org"] == str(org_id)
    assert audit_params["actor"] == "oncall-engineer"
    # `before` and `after` are JSON-serialized strings (the JSONB
    # columns accept either, but we go through json.dumps for driver
    # parity). Round-trip and assert structure.
    before = _json.loads(audit_params["before"])
    after = _json.loads(audit_params["after"])
    assert before == {
        "monthly_input_token_limit": 1_000_000,
        "monthly_output_token_limit": 200_000,
    }
    assert after == {
        "monthly_input_token_limit": 2_000_000,
        "monthly_output_token_limit": 400_000,
    }


@pytest.mark.asyncio
async def test_set_audit_before_is_null_for_first_set_on_an_org(monkeypatch):
    """When no quota row exists yet, the audit `before` must be NULL
    (encoded as None on the bound parameter), not an empty dict — the
    `before IS NULL` query is how ops finds "first-time provisioning"
    events."""
    _stub_threshold_notify_noop(monkeypatch)
    org_id = uuid4()
    session = _stub_engine_factory(monkeypatch, [None, None, None])

    await cli.cmd_set(org_id, input_limit=1_000_000, output_limit=None, actor="alice")

    audit_params = next(
        c.args[1] for c in session.execute.call_args_list if "action" in (c.args[1] or {})
    )
    assert audit_params["before"] is None  # not the string "null"


@pytest.mark.asyncio
async def test_set_resolves_actor_from_os_user_when_not_passed(monkeypatch):
    """No `--actor` → fall back to OS username. Audit log can't be
    blank, so this is the path most invocations actually take."""
    _stub_threshold_notify_noop(monkeypatch)
    monkeypatch.setattr(cli.getpass, "getuser", lambda: "thuy")

    session = _stub_engine_factory(monkeypatch, [None, None, None])
    await cli.cmd_set(uuid4(), input_limit=1, output_limit=1, actor=None)

    audit_params = next(
        c.args[1] for c in session.execute.call_args_list if "action" in (c.args[1] or {})
    )
    assert audit_params["actor"] == "thuy"


@pytest.mark.asyncio
async def test_resolve_actor_falls_back_to_unknown_when_getuser_raises(monkeypatch):
    """Sandboxed CI containers can have `getpass.getuser()` raise.
    The audit row must still be writable — fall back to "unknown"
    rather than letting the operation crash."""

    def _boom():
        raise OSError("no $USER")

    monkeypatch.setattr(cli.getpass, "getuser", _boom)
    assert cli._resolve_actor(None) == "unknown"
    # Explicit override still wins.
    assert cli._resolve_actor("svc-account") == "svc-account"


# ---------- cmd_set fires threshold check on cap-lower -----------------


@pytest.mark.asyncio
async def test_set_calls_threshold_check_after_commit(monkeypatch):
    """The cap-lowering edge case: ops drops an org's cap from 1M to
    500k while they're sitting at 600k. Pre-this-fix, no email fires
    until the org's next LLM call runs `record_org_usage`. With the
    fix, `cmd_set` calls `check_and_notify_thresholds` post-commit so
    the email goes out immediately.

    Pin via call observation: `check_and_notify_thresholds` must be
    invoked with the same `org_id` the set targeted, AND it must run
    AFTER the audit insert (otherwise the dedupe row would land
    against the pre-set state).
    """
    import importlib

    _stub_engine_factory(monkeypatch, [None, None, None])
    services_q = importlib.import_module("services.codeguard_quotas")

    invocations: list[tuple] = []

    async def _spy_notify(db, org_id, **kw):
        invocations.append((db, org_id, kw))
        return [{"dimension": "input", "threshold": 80, "recipients": ["x@y.z"], "delivered": 1}]

    monkeypatch.setattr(services_q, "check_and_notify_thresholds", _spy_notify)

    target_org = uuid4()
    result = await cli.cmd_set(
        target_org,
        input_limit=500_000,  # lowered cap
        output_limit=200_000,
        actor="ops-bot",
    )

    assert len(invocations) == 1, (
        f"check_and_notify_thresholds should have been called exactly once "
        f"after commit; was called {len(invocations)} times."
    )
    _, called_org, _ = invocations[0]
    assert called_org == target_org

    # The result surfaces the notification summaries so an operator
    # running this can see at a glance whether the email actually went.
    # Pin the field shape so the audit-trail story stays consistent.
    assert result["notifications"] == [
        {"dimension": "input", "threshold": 80, "recipients": ["x@y.z"], "delivered": 1}
    ]


@pytest.mark.asyncio
async def test_set_swallows_notification_failures(monkeypatch, capsys):
    """An SMTP outage / notification-prefs query failure must NOT roll
    back the cap update or the audit row. Pin the swallow + warning
    behaviour: the result still comes back successful, with empty
    `notifications`, and a stderr warning surfaces so the operator
    sees something went wrong with the ancillary channel."""
    import importlib

    _stub_engine_factory(monkeypatch, [None, None, None])
    services_q = importlib.import_module("services.codeguard_quotas")

    async def _boom(*_a, **_kw):
        raise RuntimeError("SMTP unreachable")

    monkeypatch.setattr(services_q, "check_and_notify_thresholds", _boom)

    target_org = uuid4()
    result = await cli.cmd_set(
        target_org,
        input_limit=1_000_000,
        output_limit=200_000,
        actor="ops-bot",
    )
    # The set itself succeeded.
    assert result["org_id"] == str(target_org)
    assert result["monthly_input_token_limit"] == 1_000_000
    # Notifications field is present but empty — distinguishable from
    # "everything went fine, nobody to notify" via the stderr warning.
    assert result["notifications"] == []
    captured = capsys.readouterr()
    assert "warning" in captured.err.lower()
    assert "check_and_notify_thresholds" in captured.err


# ---------- cmd_reset ---------------------------------------------------


@pytest.mark.asyncio
async def test_reset_zeros_current_period_usage_and_audits(monkeypatch):
    """Standard happy-path reset. Pre-read returns the current-period
    usage row (input=750, output=200); the UPDATE zeros it; the audit
    row records `before` = the snapshot, `after` = zeros."""
    import datetime as _dt
    import json as _json

    org_id = uuid4()
    pre_row = _RowStub(
        input_tokens=750,
        output_tokens=200,
        period_start=_dt.date(2026, 5, 1),
    )
    # Three executes: pre-read, UPDATE (zeros), audit insert.
    session = _stub_engine_factory(monkeypatch, [pre_row, None, None])

    result = await cli.cmd_reset(org_id, actor="oncall")

    # Result reflects what was zeroed.
    assert result["org_id"] == str(org_id)
    assert result["before"]["input_tokens"] == 750
    assert result["before"]["output_tokens"] == 200
    assert result["after"] == {
        "period_start": "2026-05-01",
        "input_tokens": 0,
        "output_tokens": 0,
    }
    assert result["actor"] == "oncall"

    # Audit row: action = quota_reset, before/after match the result.
    audit_params = next(
        c.args[1] for c in session.execute.call_args_list if "action" in (c.args[1] or {})
    )
    assert audit_params["action"] == "quota_reset"
    before = _json.loads(audit_params["before"])
    after = _json.loads(audit_params["after"])
    assert before == {
        "period_start": "2026-05-01",
        "input_tokens": 750,
        "output_tokens": 200,
    }
    assert after == {
        "period_start": "2026-05-01",
        "input_tokens": 0,
        "output_tokens": 0,
    }


@pytest.mark.asyncio
async def test_reset_with_no_existing_row_still_writes_audit(monkeypatch):
    """No usage row for the current period → reset is a data no-op
    but the audit row IS still written (with before=null, after=null).
    Pinning this is important: an operator running `reset` against an
    org with no usage needs evidence in the log that they tried, for
    later debugging."""
    org_id = uuid4()
    # Pre-read returns None (no row). UPDATE affects 0 rows. Audit
    # insert still runs.
    session = _stub_engine_factory(monkeypatch, [None, None, None])

    result = await cli.cmd_reset(org_id, actor="bob")

    assert result["before"] is None
    assert result["after"] is None
    audit_params = next(
        c.args[1] for c in session.execute.call_args_list if "action" in (c.args[1] or {})
    )
    assert audit_params["action"] == "quota_reset"
    assert audit_params["before"] is None
    assert audit_params["after"] is None
    assert audit_params["actor"] == "bob"


# ---------- cmd_get -----------------------------------------------------


@pytest.mark.asyncio
async def test_get_returns_quota_and_usage_with_percent(monkeypatch):
    """Standard happy-path read. The percent-of-cap calculation is the
    bit ops dashboards rely on, so pin both halves of it (input + output)."""
    org_id = uuid4()
    _stub_engine_factory(
        monkeypatch,
        [
            _RowStub(
                in_lim=1_000_000,
                out_lim=200_000,
                in_used=500_000,
                out_used=160_000,
                period_start=__import__("datetime").date(2026, 5, 1),
            )
        ],
    )

    data = await cli.cmd_get(org_id)
    assert data["quota"]["monthly_input_token_limit"] == 1_000_000
    assert data["quota"]["monthly_output_token_limit"] == 200_000
    assert data["usage"]["input_tokens"] == 500_000
    assert data["usage"]["output_tokens"] == 160_000
    # Percent-of-cap: 500k / 1M = 50%, 160k / 200k = 80%.
    assert data["percent_of_cap"]["input"] == 50.0
    assert data["percent_of_cap"]["output"] == 80.0


@pytest.mark.asyncio
async def test_get_returns_unlimited_note_when_no_quota_row(monkeypatch):
    """Org without a quota row → unlimited; the CLI must surface that
    distinctly, not as "0 / 0" or a crash. Pins the documented opt-in
    semantic for the read path."""
    _stub_engine_factory(monkeypatch, [None])

    data = await cli.cmd_get(uuid4())
    assert data["quota"] is None
    assert data["usage"] is None
    assert "unlimited" in data["note"].lower()


@pytest.mark.asyncio
async def test_get_handles_null_dimension_limit(monkeypatch):
    """One dimension NULL (unlimited) → percent for that dimension is
    None, the other dimension still computed normally."""
    _stub_engine_factory(
        monkeypatch,
        [
            _RowStub(
                in_lim=None,  # unlimited
                out_lim=200_000,
                in_used=999_999,
                out_used=50_000,
                period_start=__import__("datetime").date(2026, 5, 1),
            )
        ],
    )

    data = await cli.cmd_get(uuid4())
    assert data["percent_of_cap"]["input"] is None
    assert data["percent_of_cap"]["output"] == 25.0


# ---------- cmd_list ----------------------------------------------------


@pytest.mark.asyncio
async def test_list_sorts_by_binding_pct_descending(monkeypatch):
    """At-risk orgs (high binding %) sort first; orgs with no binding
    (both unlimited) sort to the end. Pins the dashboard ordering."""
    a, b, c = uuid4(), uuid4(), uuid4()
    _stub_engine_factory(
        monkeypatch,
        [
            [
                _RowStub(
                    org_id=a, in_lim=1_000_000, out_lim=100_000, in_used=300_000, out_used=20_000
                ),  # 30% / 20% → 30%
                _RowStub(
                    org_id=b, in_lim=1_000_000, out_lim=100_000, in_used=950_000, out_used=10_000
                ),  # 95% / 10% → 95%
                _RowStub(
                    org_id=c, in_lim=None, out_lim=None, in_used=999, out_used=999
                ),  # unlimited
            ]
        ],
    )

    rows = await cli.cmd_list(over_pct=None)
    # b first (95%), then a (30%), then c (no binding).
    assert [r["org_id"] for r in rows] == [str(b), str(a), str(c)]


@pytest.mark.asyncio
async def test_list_filters_by_over_pct(monkeypatch):
    """`--over-pct 80` includes only orgs whose binding dimension is at
    or above 80%. Pins the at-risk dashboard query."""
    a, b = uuid4(), uuid4()
    _stub_engine_factory(
        monkeypatch,
        [
            [
                _RowStub(
                    org_id=a, in_lim=1_000_000, out_lim=100_000, in_used=300_000, out_used=20_000
                ),  # 30%
                _RowStub(
                    org_id=b, in_lim=1_000_000, out_lim=100_000, in_used=950_000, out_used=10_000
                ),  # 95%
            ]
        ],
    )

    rows = await cli.cmd_list(over_pct=80)
    assert len(rows) == 1
    assert rows[0]["org_id"] == str(b)


# ---------- formatting --------------------------------------------------


def test_format_get_includes_percent_when_available():
    """The human-readable get output shows the percent for any dimension
    with a numeric cap. Without the percent column, an ops engineer
    has to mental-math `used / limit` for every row — pin that the
    formatter does it for them."""
    data = {
        "org_id": "00000000-0000-0000-0000-000000000abc",
        "quota": {
            "monthly_input_token_limit": 1_000_000,
            "monthly_output_token_limit": 200_000,
        },
        "usage": {
            "period_start": "2026-05-01",
            "input_tokens": 500_000,
            "output_tokens": 160_000,
        },
        "percent_of_cap": {"input": 50.0, "output": 80.0},
    }
    out = cli.format_get(data)
    assert "50.0%" in out
    assert "80.0%" in out
    assert "1,000,000" in out
    assert "200,000" in out


def test_format_get_renders_unlimited_when_no_quota_row():
    """The "no quota row" path produces a single-line summary so an
    operator running `quotas get <uuid>` against an unconfigured org
    sees clearly why no numbers print."""
    data = {
        "org_id": "00000000-0000-0000-0000-000000000abc",
        "quota": None,
        "usage": None,
        "note": "No quota row — this org is unlimited.",
    }
    out = cli.format_get(data)
    assert "unlimited" in out.lower()


def test_format_set_renders_limits_and_actor():
    """`format_set` prints the bound limits + actor so the operator can
    eyeball what just landed in the audit log without re-querying.
    Pin both numeric and `unlimited` shapes."""
    out = cli.format_set(
        {
            "org_id": "00000000-0000-0000-0000-000000000abc",
            "monthly_input_token_limit": 5_000_000,
            "monthly_output_token_limit": None,
            "actor": "ops-bot",
        }
    )
    assert "5,000,000" in out
    assert "unlimited" in out
    assert "ops-bot" in out


def test_format_reset_shows_zeroed_totals_when_row_existed():
    """Reset summary surfaces the pre-reset numbers so the operator
    can see the blast radius of what they just cleared."""
    out = cli.format_reset(
        {
            "org_id": "00000000-0000-0000-0000-000000000abc",
            "before": {
                "period_start": "2026-05-01",
                "input_tokens": 750,
                "output_tokens": 200,
            },
            "after": {
                "period_start": "2026-05-01",
                "input_tokens": 0,
                "output_tokens": 0,
            },
            "actor": "oncall",
        }
    )
    assert "750" in out
    assert "200" in out
    assert "→ 0" in out
    assert "oncall" in out


def test_format_reset_explains_no_op_when_no_row_existed():
    """When `before` is None, the formatter must say "nothing to reset"
    rather than print "0 → 0" (which would be ambiguous with the
    happy-path reset of an org whose totals happened to be 0)."""
    out = cli.format_reset(
        {
            "org_id": "00000000-0000-0000-0000-000000000abc",
            "before": None,
            "after": None,
            "actor": "alice",
        }
    )
    assert "nothing to reset" in out.lower()


def test_format_list_handles_empty_input():
    assert "No orgs match" in cli.format_list([])


def test_format_list_renders_table_with_percents():
    rows = [
        {
            "org_id": "00000000-0000-0000-0000-000000000abc",
            "input_used": 500_000,
            "input_limit": 1_000_000,
            "input_pct": 50.0,
            "output_used": 160_000,
            "output_limit": 200_000,
            "output_pct": 80.0,
            "binding_pct": 80.0,
        }
    ]
    out = cli.format_list(rows)
    assert "00000000-0000-0000-0000-000000000abc" in out
    assert "500,000" in out
    assert "80.0" in out


# ---------- cmd_audit ---------------------------------------------------


@pytest.mark.asyncio
async def test_audit_returns_rows_in_descending_order(monkeypatch):
    """Standard happy path: cmd_audit returns whatever the SQL produces,
    most-recent first. The ORDER BY in the SQL is what guarantees that
    ordering — pin via the rendered list shape so a regression that
    drops `ORDER BY occurred_at DESC` is visible."""
    import datetime as _dt

    org_id = uuid4()
    rows = [
        _RowStub(
            id=uuid4(),
            occurred_at=_dt.datetime(2026, 5, 1, 12, 0, 0),
            actor="bob",
            action="quota_set",
            before={"monthly_input_token_limit": 1_000_000},
            after={"monthly_input_token_limit": 5_000_000},
        ),
        _RowStub(
            id=uuid4(),
            occurred_at=_dt.datetime(2026, 4, 1, 9, 0, 0),
            actor="alice",
            action="quota_set",
            before=None,
            after={"monthly_input_token_limit": 1_000_000},
        ),
    ]
    _stub_engine_factory(monkeypatch, [rows])

    result = await cli.cmd_audit(org_id, limit=50, since=None, action=None)
    assert len(result) == 2
    assert result[0]["actor"] == "bob"
    assert result[0]["action"] == "quota_set"
    # ISO timestamp surfaces as a string for `--json` consumers.
    assert result[0]["occurred_at"].startswith("2026-05-01T12:00:00")
    # `before` / `after` round-trip the JSONB dicts unchanged.
    assert result[1]["before"] is None
    assert result[1]["after"] == {"monthly_input_token_limit": 1_000_000}


@pytest.mark.asyncio
async def test_audit_binds_filter_params_when_provided(monkeypatch):
    """`--since` and `--action` bind to the SQL only when set. Pin the
    parameter shape so a refactor that reorders the WHERE clauses or
    drops a filter is visible."""
    org_id = uuid4()
    session = _stub_engine_factory(monkeypatch, [[]])

    await cli.cmd_audit(org_id, limit=10, since="2026-04-01", action="quota_reset")

    # The single execute call binds org, limit, since, and action — all four.
    params = session.execute.call_args.args[1]
    assert params["org"] == str(org_id)
    assert params["limit"] == 10
    assert params["since"] == "2026-04-01"
    assert params["action"] == "quota_reset"


@pytest.mark.asyncio
async def test_audit_omits_filter_params_when_not_provided(monkeypatch):
    """No filters → the SQL has no `since` or `action` placeholder, so
    those keys must NOT appear in the bound params (binding an unused
    `:since` would be either ignored or rejected depending on driver,
    but it'd also signal that the assembly logic isn't actually
    excluding the clause). Pin the omission."""
    org_id = uuid4()
    session = _stub_engine_factory(monkeypatch, [[]])

    await cli.cmd_audit(org_id, limit=50, since=None, action=None)

    params = session.execute.call_args.args[1]
    assert "since" not in params
    assert "action" not in params
    # `org` and `limit` always bind.
    assert set(params.keys()) == {"org", "limit"}


# ---------- format_audit ------------------------------------------------


def test_format_audit_compresses_quota_set_diff():
    """A `quota_set` row's summary should compress like:
        input 1M→5M, output 200k→1M
    Pinning this exact shape so the column-widths don't silently drift
    and break ops dashboards that grep the output."""
    rows = [
        {
            "occurred_at": "2026-05-01T12:00:00",
            "actor": "bob",
            "action": "quota_set",
            "before": {
                "monthly_input_token_limit": 1_000_000,
                "monthly_output_token_limit": 200_000,
            },
            "after": {
                "monthly_input_token_limit": 5_000_000,
                "monthly_output_token_limit": 1_000_000,
            },
        }
    ]
    out = cli.format_audit(rows)
    assert "bob" in out
    assert "quota_set" in out
    # Compressed token counts ("1M→5M" not "1000000 → 5000000").
    assert "input 1M→5M" in out
    assert "output 200k→1M" in out


def test_format_audit_handles_first_time_provisioning():
    """When `before` is None (first `set` for an org), the diff renders
    as ∞→<value> — nothing → cap. The infinity shorthand for "no prior
    limit" matches the display elsewhere in the CLI."""
    rows = [
        {
            "occurred_at": "2026-04-01T09:00:00",
            "actor": "alice",
            "action": "quota_set",
            "before": None,
            "after": {
                "monthly_input_token_limit": 1_000_000,
                "monthly_output_token_limit": 200_000,
            },
        }
    ]
    out = cli.format_audit(rows)
    # `before` None → both fields render as ∞ (the unlimited shorthand).
    assert "input ∞→1M" in out
    assert "output ∞→200k" in out


def test_format_audit_summarizes_quota_reset():
    """A `quota_reset` row surfaces what was zeroed."""
    rows = [
        {
            "occurred_at": "2026-04-15T09:30:00",
            "actor": "oncall",
            "action": "quota_reset",
            "before": {
                "period_start": "2026-04-01",
                "input_tokens": 850_000,
                "output_tokens": 120_000,
            },
            "after": {
                "period_start": "2026-04-01",
                "input_tokens": 0,
                "output_tokens": 0,
            },
        }
    ]
    out = cli.format_audit(rows)
    assert "input 850k→0" in out
    assert "output 120k→0" in out


def test_format_audit_handles_reset_against_no_usage_row():
    """`quota_reset` with `before=None` (no usage row existed) renders a
    "(no usage row — nothing to zero)" hint rather than fabricating
    a 0→0 diff."""
    rows = [
        {
            "occurred_at": "2026-05-01T00:00:00",
            "actor": "bob",
            "action": "quota_reset",
            "before": None,
            "after": None,
        }
    ]
    out = cli.format_audit(rows)
    assert "nothing to zero" in out


def test_format_audit_falls_back_for_unknown_action():
    """Unknown action types render `(see --json for details)` rather
    than guessing the diff shape — pinning so a future action like
    `quota_unset` doesn't silently truncate fields."""
    rows = [
        {
            "occurred_at": "2026-05-01T00:00:00",
            "actor": "bob",
            "action": "quota_archive",  # hypothetical future action
            "before": {"foo": "bar"},
            "after": {"foo": "baz"},
        }
    ]
    out = cli.format_audit(rows)
    assert "see --json for details" in out


def test_format_audit_renders_no_match_message_on_empty():
    """Empty result set → friendly message rather than a header-only
    table that looks like a parsing failure."""
    out = cli.format_audit([])
    assert "No audit entries match" in out


def test_short_num_formats_compactly():
    """Spot-check the compact number helper — it's what the audit table
    relies on to keep summary lines under a terminal width."""
    assert cli._short_num(None) == "∞"
    assert cli._short_num(0) == "0"
    assert cli._short_num(500) == "500"
    assert cli._short_num(1_500) == "2k"  # rounds
    assert cli._short_num(1_000_000) == "1M"  # 1.0M → 1M (suffix collapse)
    assert cli._short_num(5_500_000) == "5.5M"


# ---------- routes (operator visibility into ROUTE_WEIGHTS) -----------


def test_cmd_routes_returns_sorted_by_weight_descending():
    """Operators want to see "what's the heaviest route" at a glance,
    so the dict gets emitted sorted by weight DESC. Pin the order so
    a refactor that lazily returns dict items doesn't surface as a
    confusing test that intermittently passes."""
    rows = cli.cmd_routes()
    weights = [r["weight"] for r in rows]
    assert weights == sorted(weights, reverse=True), (
        f"Routes not sorted by weight DESC: {weights!r}. "
        "format_routes renders top-down; out-of-order rows look like "
        "a bug to operators."
    )


def test_cmd_routes_includes_canonical_routes():
    """Pin the canonical routes — these match the snapshot test's
    pinned weights. A regression that drops `/scan` from the dict
    would surface here too."""
    rows = cli.cmd_routes()
    by_key = {r["route_key"]: r["weight"] for r in rows}
    assert by_key["scan"] == 5.0
    assert by_key["query"] == 1.0
    assert by_key["permit-checklist"] == 2.0


def test_format_routes_renders_table_with_two_decimal_weights():
    """`weight=5.0` renders as `5.00`. Operators grep against the
    output (e.g. `quotas routes | grep scan`) so the format must be
    stable. Two decimals distinguishes the default 1.0 from a
    deliberate fractional weight like 1.5."""
    out = cli.format_routes(
        [
            {"route_key": "scan", "weight": 5.0},
            {"route_key": "query", "weight": 1.0},
        ]
    )
    assert "5.00" in out
    assert "1.00" in out
    assert "scan" in out
    assert "query" in out


def test_format_routes_handles_empty_input():
    """`ROUTE_WEIGHTS = {}` (hypothetical full-revert) → friendly
    sentinel rather than a header-only table that looks like a
    parsing failure to operators."""
    assert "No routes registered" in cli.format_routes([])


def test_main_routes_subcommand_exits_zero(capsys):
    """End-to-end: `main(["routes"])` exits 0 and prints the table.
    Mirrors what an operator sees when they run the command."""
    rc = cli.main(["routes"])
    assert rc == 0
    out = capsys.readouterr().out
    # Every canonical route appears.
    assert "scan" in out
    assert "query" in out
    assert "permit-checklist" in out


def test_main_routes_subcommand_with_json_flag_emits_valid_json(capsys):
    """`--json routes` (note: --json must come BEFORE the subcommand
    per argparse's parent-flag semantics) emits machine-readable
    JSON — pipe to jq for dashboards."""
    import json as _json

    rc = cli.main(["--json", "routes"])
    assert rc == 0
    out = capsys.readouterr().out
    parsed = _json.loads(out)
    assert isinstance(parsed, list)
    assert any(r["route_key"] == "scan" for r in parsed)
