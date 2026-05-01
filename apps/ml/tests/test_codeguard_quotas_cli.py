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
