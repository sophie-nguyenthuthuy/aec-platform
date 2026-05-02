"""Tests for `services.codeguard_quotas` and route-level 429 enforcement.

The quota helpers (`check_org_quota`, `record_org_usage`) are tested
against a stubbed AsyncSession so we don't need a live Postgres for
Tier 2. The route-level enforcement test confirms that an over-quota
org gets a structured 429 from the codeguard endpoints — the load-
bearing user-visible behaviour.

The integration test for the actual SQL (UPSERT semantics, `date_trunc`
behaviour) lives in Tier 3 and runs against the service-container DB
in CI; it's the equivalent of how other modules split helper logic
(unit-tested with mocks) from SQL semantics (integration-tested with
the real DB).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

pytestmark = pytest.mark.asyncio


# ---------- check_org_quota ------------------------------------------------


class _RowStub:
    """Mimics `Row` so `.first()` returns something with attribute access."""

    def __init__(self, **fields):
        for k, v in fields.items():
            setattr(self, k, v)


def _execute_returning_first(row):
    """Build an AsyncMock for `db.execute` that returns a Result whose
    `.first()` gives back the supplied row stub. Mirrors how
    SQLAlchemy's async path actually shapes results."""
    result = MagicMock()
    result.first.return_value = row
    return AsyncMock(return_value=result)


async def test_check_quota_returns_unlimited_when_no_quota_row():
    """The opt-in enforcement contract: orgs without an explicit quota
    row are not blocked. Pin so the rollout doesn't accidentally start
    rejecting unrelated tenants."""
    from services.codeguard_quotas import check_org_quota

    db = MagicMock()
    db.execute = _execute_returning_first(None)  # no row → unlimited

    result = await check_org_quota(db, uuid4())
    assert result.over_limit is False
    assert result.limit_kind == "unlimited"
    assert result.limit is None


async def test_check_quota_under_limit_passes():
    """Quota row exists, usage is below the limit on both dimensions →
    `over_limit=False`."""
    from services.codeguard_quotas import check_org_quota

    db = MagicMock()
    db.execute = _execute_returning_first(
        _RowStub(
            monthly_input_token_limit=1_000_000,
            monthly_output_token_limit=200_000,
            input_used=300_000,
            output_used=50_000,
        )
    )

    result = await check_org_quota(db, uuid4())
    assert result.over_limit is False
    assert result.limit_kind == "unlimited"


async def test_check_quota_blocks_when_input_limit_crossed():
    """The binding dimension surfaces in `limit_kind` so the 429
    message can point at the right cap. Input crossed first."""
    from services.codeguard_quotas import check_org_quota

    db = MagicMock()
    db.execute = _execute_returning_first(
        _RowStub(
            monthly_input_token_limit=1_000_000,
            monthly_output_token_limit=200_000,
            input_used=1_000_000,  # at the limit
            output_used=50_000,
        )
    )

    result = await check_org_quota(db, uuid4())
    assert result.over_limit is True
    assert result.limit_kind == "input"
    assert result.used == 1_000_000
    assert result.limit == 1_000_000


async def test_check_quota_blocks_when_output_limit_crossed():
    """Output limit alone is enough to block — orgs typically pin on
    output (Anthropic prices output ~5× input). Pin both code paths."""
    from services.codeguard_quotas import check_org_quota

    db = MagicMock()
    db.execute = _execute_returning_first(
        _RowStub(
            monthly_input_token_limit=10_000_000,  # nowhere near
            monthly_output_token_limit=200_000,
            input_used=500_000,
            output_used=210_000,  # over
        )
    )

    result = await check_org_quota(db, uuid4())
    assert result.over_limit is True
    assert result.limit_kind == "output"
    assert result.used == 210_000


async def test_check_quota_handles_null_limit_per_dimension():
    """A quota row with NULL on one dimension means "unlimited on that
    dimension." Org pins only on the dimension that has a number."""
    from services.codeguard_quotas import check_org_quota

    db = MagicMock()
    db.execute = _execute_returning_first(
        _RowStub(
            monthly_input_token_limit=None,  # unlimited input
            monthly_output_token_limit=200_000,
            input_used=999_999_999,  # huge but no cap
            output_used=50_000,
        )
    )

    result = await check_org_quota(db, uuid4())
    assert result.over_limit is False
    assert result.limit_kind == "unlimited"


async def test_check_quota_handles_quota_with_no_usage_row():
    """Org has a quota assigned but never spent any tokens — the LEFT
    JOIN gives 0 used, not an error. First-use case for newly-created
    orgs."""
    from services.codeguard_quotas import check_org_quota

    db = MagicMock()
    db.execute = _execute_returning_first(
        _RowStub(
            monthly_input_token_limit=1_000_000,
            monthly_output_token_limit=200_000,
            input_used=0,  # COALESCE handled this in SQL
            output_used=0,
        )
    )

    result = await check_org_quota(db, uuid4())
    assert result.over_limit is False


# ---------- record_org_usage -----------------------------------------------


async def test_record_usage_skips_db_write_when_zero_tokens():
    """A request that consumed nothing (e.g. pure HyDE cache hit, or
    an early-aborted call) skips the DB hit entirely. Verified by
    asserting `db.execute` is NOT called — the no-op guard is what
    keeps free-cache requests truly free of DB load."""
    from services.codeguard_quotas import record_org_usage

    db = MagicMock()
    db.execute = AsyncMock()

    await record_org_usage(db, uuid4(), input_tokens=0, output_tokens=0)
    db.execute.assert_not_called()


async def test_record_usage_calls_db_when_tokens_present():
    """Non-zero tokens → exactly one DB execute (the UPSERT). The
    actual SQL semantics (ON CONFLICT, date_trunc) are validated by
    the Tier 3 integration test against a real Postgres."""
    from services.codeguard_quotas import record_org_usage

    db = MagicMock()
    db.execute = AsyncMock()

    org_id = uuid4()
    await record_org_usage(db, org_id, input_tokens=500, output_tokens=100)
    assert db.execute.call_count == 1
    # Inspect the parameters bound to the UPSERT — pin the param shape
    # so a future refactor of the SQL doesn't accidentally swap
    # input/output token assignment.
    args, _ = db.execute.call_args
    params = args[1]
    assert params["org_id"] == str(org_id)
    assert params["in_tok"] == 500
    assert params["out_tok"] == 100


# ---------- vi-VN number formatter -----------------------------------------


async def test_cap_check_ticks_429_counter_and_observes_latency(client, monkeypatch):
    """Pin the observability contract on the cap-check helper:

      * `codeguard_quota_429_total{limit_kind}` ticks once per refused
        request, labelled with the binding dimension.
      * `codeguard_quota_check_duration_seconds` records ONE observation
        per cap-check (regardless of allow/deny). Ops need this to spot
        the cap-check inflating p95 on LLM routes.

    Without these metrics, dashboards can't answer "are we capping out
    tenants more after the latest deploy" without grepping pod logs —
    which is exactly the scrap-the-fleet workflow the prometheus
    exporter exists to avoid.
    """
    from core import metrics
    from services.codeguard_quotas import QuotaCheckResult

    # Snapshot the relevant counter / histogram state BEFORE the call
    # so the assertion is robust to other tests in this file having
    # already fired the cap-check (the metrics module is process-wide
    # state). We diff before/after rather than asserting absolute counts.
    before_429 = metrics.codeguard_quota_429_total._values.get(("input",), 0.0)
    before_obs = metrics.codeguard_quota_check_duration_seconds._observations.get(
        (), [0.0, 0.0]
    )
    before_count = before_obs[1] if len(before_obs) >= 2 else 0.0

    async def _over_quota(_db, _org_id):
        return QuotaCheckResult(
            over_limit=True, limit_kind="input", used=1_500_000, limit=1_000_000
        )

    monkeypatch.setattr("services.codeguard_quotas.check_org_quota", _over_quota)

    res = await client.post(
        "/api/v1/codeguard/query",
        json={"question": "blocked"},
    )
    assert res.status_code == 429

    after_429 = metrics.codeguard_quota_429_total._values.get(("input",), 0.0)
    after_count = (
        metrics.codeguard_quota_check_duration_seconds._observations.get((), [0.0, 0.0])[1]
    )
    assert after_429 == before_429 + 1, (
        "Counter `codeguard_quota_429_total{limit_kind=input}` should have "
        f"incremented by exactly 1 (was {before_429}, now {after_429}). "
        "Did the cap-check helper stop calling `.inc()`?"
    )
    assert after_count == before_count + 1, (
        f"Histogram should have observed exactly one new sample (was "
        f"count={before_count}, now {after_count}). Either the helper "
        "stopped wrapping the SELECT or the try/finally guard regressed."
    )


async def test_cap_check_does_not_tick_429_when_under_limit(client, monkeypatch):
    """The histogram observation fires on every cap-check (under or
    over), but the 429 counter must ONLY tick on refused requests. A
    regression that increments the counter unconditionally would inflate
    the dashboard's "tenants getting capped" view by every successful
    request — silent but very wrong."""
    from core import metrics
    from services.codeguard_quotas import QuotaCheckResult

    before_429_input = metrics.codeguard_quota_429_total._values.get(("input",), 0.0)
    before_429_output = metrics.codeguard_quota_429_total._values.get(("output",), 0.0)
    before_count = (
        metrics.codeguard_quota_check_duration_seconds._observations.get((), [0.0, 0.0])[1]
    )

    async def _under_quota(_db, _org_id):
        return QuotaCheckResult(over_limit=False, limit_kind="unlimited", used=0, limit=None)

    monkeypatch.setattr("services.codeguard_quotas.check_org_quota", _under_quota)

    # Call a cheap LLM-touching route. We don't actually need the LLM
    # to run; we just need to traverse the cap-check helper. Use the
    # /quota route — wait, that doesn't run the cap-check. Use /query
    # but stub the LLM via the same monkeypatch the file already does
    # implicitly via mock_llm fixture in other tests. Simplest: call
    # /query and let it 500 if the LLM stub is missing — we don't
    # assert on the response here, only the metric deltas.
    try:
        await client.post(
            "/api/v1/codeguard/query",
            json={"question": "ok"},
        )
    except Exception:
        # Don't care about the LLM-side outcome; the cap-check fired
        # before any LLM call. Pinning the metric deltas is the point.
        pass

    after_429_input = metrics.codeguard_quota_429_total._values.get(("input",), 0.0)
    after_429_output = metrics.codeguard_quota_429_total._values.get(("output",), 0.0)
    after_count = (
        metrics.codeguard_quota_check_duration_seconds._observations.get((), [0.0, 0.0])[1]
    )

    # Counter unchanged on the under-limit path.
    assert after_429_input == before_429_input
    assert after_429_output == before_429_output
    # Histogram still got an observation (cap-check ran).
    assert after_count >= before_count + 1


async def test_format_vi_int_uses_dot_grouping_not_comma():
    """vi-VN convention: thousands separator is `.`, decimal separator
    is `,`. The router-side helper has to match what the banner / quota
    page render so the 429 toast doesn't read jarring against the
    surrounding UI. A regression to Python's default `:,` formatting
    would silently re-introduce English-style grouping in the only
    user-facing string the cap-check produces."""
    from routers.codeguard import _format_vi_int

    assert _format_vi_int(1_500_000) == "1.500.000"
    assert _format_vi_int(0) == "0"
    assert _format_vi_int(999) == "999"
    assert _format_vi_int(1_000) == "1.000"
    # NULL limit (the unlimited-on-this-axis path that tripped over_limit
    # somehow) renders as "?" rather than crashing the format.
    assert _format_vi_int(None) == "?"


# ---------- Route enforcement: structured 429 ------------------------------


async def test_query_route_returns_429_when_org_over_quota(client, monkeypatch):
    """End-to-end: an over-quota org calling /query gets a 429 with the
    standard envelope shape. The pipeline is NOT invoked — proven by
    not setting up `mock_llm.query`, which would fail loudly if the
    route somehow reached the LLM layer."""
    from services.codeguard_quotas import QuotaCheckResult

    # Force the quota check to report over-limit. We patch at the
    # service-module level so the route's import resolves to our stub.
    async def _over_quota(_db, _org_id):
        return QuotaCheckResult(over_limit=True, limit_kind="output", used=210_000, limit=200_000)

    monkeypatch.setattr("services.codeguard_quotas.check_org_quota", _over_quota)

    # Defensive: if record_usage somehow gets called, no-op (the dep
    # raises before reaching it, but pin the contract).
    async def _noop_record(*_a, **_kw):
        return None

    monkeypatch.setattr("services.codeguard_quotas.record_org_usage", _noop_record)

    res = await client.post(
        "/api/v1/codeguard/query",
        json={"question": "Will not be answered, quota exceeded"},
    )
    assert res.status_code == 429
    body = res.json()
    assert body["errors"] is not None
    msg = body["errors"][0]["message"]
    # The dimension label ("output") is preserved as-is so it matches
    # the banner copy elsewhere in the UI ("hạn mức output"). The
    # surrounding copy is Vietnamese — pin a substring rather than the
    # whole message so a future tweak of the prefix doesn't trip this
    # unrelated assertion.
    assert "output" in msg
    assert "Đã vượt hạn mức" in msg, (
        f"Expected the Vietnamese 429 copy ('Đã vượt hạn mức ...') but got: {msg!r}. "
        "Did the message regress to the previous English string?"
    )
    # vi-VN dot grouping, NOT comma grouping. Pinning both halves
    # because a regression to `:,` formatting would silently render
    # `210,000 / 200,000` in a Vietnamese error string — visibly
    # inconsistent with the surrounding banner / quota page.
    assert "210.000" in msg
    assert "200.000" in msg
    # The 429 must surface a `details_url` pointing at the in-app quota
    # planning page — that's what lets the toast render a "Xem hạn mức"
    # CTA. Without this, the user sees the error but has no path from
    # "I hit the cap" to "where do I see my usage." Pin the exact URL
    # so a frontend regression that mis-routes can't slip in unnoticed.
    assert body["errors"][0]["details_url"] == "/codeguard/quota"


@pytest.mark.parametrize(
    "method,path,body",
    [
        # Each LLM-invoking route must apply the same quota gate. The
        # parametrise covers the five routes that were previously
        # unprotected — only `/query` had the inline check originally,
        # leaving the other five as free bypasses for over-quota orgs.
        ("post", "/api/v1/codeguard/query/stream", {"question": "blocked stream"}),
        (
            "post",
            "/api/v1/codeguard/scan",
            {
                "project_id": "11111111-1111-1111-1111-111111111111",
                "parameters": {"project_type": "residential"},
            },
        ),
        (
            "post",
            "/api/v1/codeguard/scan/stream",
            {
                "project_id": "11111111-1111-1111-1111-111111111111",
                "parameters": {"project_type": "residential"},
            },
        ),
        (
            "post",
            "/api/v1/codeguard/permit-checklist",
            {
                "project_id": "11111111-1111-1111-1111-111111111111",
                "jurisdiction": "Hồ Chí Minh",
                "project_type": "residential",
            },
        ),
        (
            "post",
            "/api/v1/codeguard/permit-checklist/stream",
            {
                "project_id": "11111111-1111-1111-1111-111111111111",
                "jurisdiction": "Hồ Chí Minh",
                "project_type": "residential",
            },
        ),
    ],
)
async def test_all_llm_routes_return_429_when_org_over_quota(client, monkeypatch, method, path, body):
    """Cross-route 429 contract: every LLM-invoking surface (six total —
    one Q&A, two scan, three checklist when counting both stream/non-stream
    variants) gates on the same quota check. A regression that drops the
    pre-flight from any of them re-opens a free bypass for over-quota
    orgs and would silently ship without this parametrised test catching it.

    The /query route has its own dedicated test above; this one covers
    the five routes that were unprotected at the start of this round."""
    from services.codeguard_quotas import QuotaCheckResult

    async def _over_quota(_db, _org_id):
        return QuotaCheckResult(over_limit=True, limit_kind="input", used=1_500_000, limit=1_000_000)

    monkeypatch.setattr("services.codeguard_quotas.check_org_quota", _over_quota)

    res = await getattr(client, method)(path, json=body)
    assert res.status_code == 429, (
        f"{method.upper()} {path} returned {res.status_code} instead of 429 "
        f"when over quota — the inline _check_quota_or_raise call is "
        "missing from this route or has been short-circuited."
    )
    body_json = res.json()
    assert body_json["errors"] is not None
    msg = body_json["errors"][0]["message"]
    assert "input" in msg
    assert "Đã vượt hạn mức" in msg
    # `details_url` must be present on every LLM-route 429, not just
    # /query. A regression that re-implemented the cap-check helper
    # for one route without copying the dict-detail shape would be
    # caught here.
    assert body_json["errors"][0]["details_url"] == "/codeguard/quota"


async def test_query_route_drains_telemetry_accumulator_into_record_org_usage(
    client, monkeypatch, mock_llm, make_query_response
):
    """The load-bearing contract for the cap-enforcement story.

    The previous wiring called `record_org_usage(in_tok=..., out_tok=...)`
    with kwarg names that didn't match the function's signature. Every
    call raised TypeError, got swallowed by the surrounding try/except,
    and silently produced a no-op. Result: the usage table never got
    written, so `check_org_quota` always saw 0 spend and the cap could
    never trip in real traffic.

    This test stubs the LLM via the `mock_llm` fixture (so no real
    Anthropic call) and stubs `set_telemetry_accumulator` to record
    a non-zero accumulator state — proving that the route's
    `_with_usage_recording` wrap actually drains accumulated tokens
    into `record_org_usage` with the correct kwarg names. A regression
    that re-introduces the kwarg mismatch would surface here as a
    TypeError in `record_org_usage` (visible because we don't swallow
    in this stub).
    """
    from services.codeguard_quotas import QuotaCheckResult

    async def _under_quota(_db, _org_id):
        return QuotaCheckResult(over_limit=False, limit_kind="unlimited", used=0, limit=None)

    monkeypatch.setattr("services.codeguard_quotas.check_org_quota", _under_quota)

    # Capture every call to record_org_usage so we can assert on the
    # final invocation. The `_with_usage_recording` helper short-circuits
    # when both counters are 0, so we need to seed the accumulator with
    # non-zero counts to prove the drain path actually fires.
    recorded: list[dict] = []

    async def _capturing_record(_db, org_id, *, input_tokens, output_tokens):
        recorded.append(
            {
                "org_id": org_id,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            }
        )

    monkeypatch.setattr("services.codeguard_quotas.record_org_usage", _capturing_record)

    # Have the pipeline's `set_telemetry_accumulator` populate the
    # accumulator with non-zero counts so the drain path is exercised.
    # We can't get the LLM mock to populate it (the mock_llm fixture
    # bypasses `_record_llm_call` entirely), so we hook into the bind
    # itself to seed the counters.
    from ml.pipelines import codeguard as cg_pipeline

    real_set = cg_pipeline.set_telemetry_accumulator

    def _set_with_seed(acc):
        # Mock LLM doesn't accumulate naturally; seed so the drain has
        # something to write. Real traffic gets these counts via
        # `_record_llm_call`'s on_llm_end path.
        if acc is not None:
            acc.input_tokens = 1234
            acc.output_tokens = 567
        return real_set(acc)

    monkeypatch.setattr(cg_pipeline, "set_telemetry_accumulator", _set_with_seed)

    mock_llm.query(returns=make_query_response())

    res = await client.post(
        "/api/v1/codeguard/query",
        json={"question": "Should record usage on the way out"},
    )
    assert res.status_code == 200, res.text

    # The drain fired exactly once with the seeded counts.
    assert len(recorded) == 1, (
        f"expected exactly one record_org_usage call, got {len(recorded)}: "
        "the route's _with_usage_recording wrap is missing or the helper "
        "isn't draining on success."
    )
    call = recorded[0]
    assert call["input_tokens"] == 1234
    assert call["output_tokens"] == 567


async def test_query_route_passes_through_when_org_under_quota(client, monkeypatch, mock_llm, make_query_response):
    """Mirror of the over-quota test: under-quota orgs flow through
    normally. Pin so a regression that misreads the QuotaCheckResult
    doesn't accidentally block under-quota requests."""
    from services.codeguard_quotas import QuotaCheckResult

    async def _under_quota(_db, _org_id):
        return QuotaCheckResult(over_limit=False, limit_kind="unlimited", used=0, limit=None)

    async def _noop_record(*_a, **_kw):
        return None

    monkeypatch.setattr("services.codeguard_quotas.check_org_quota", _under_quota)
    monkeypatch.setattr("services.codeguard_quotas.record_org_usage", _noop_record)

    mock_llm.query(returns=make_query_response())

    res = await client.post(
        "/api/v1/codeguard/query",
        json={"question": "Allowed by quota, should answer normally"},
    )
    assert res.status_code == 200
    assert res.json()["data"]["answer"]


# ---------- GET /quota -------------------------------------------------


async def test_quota_route_returns_unlimited_when_no_quota_row(client, fake_db, fake_auth):
    """Org with no quota row → `unlimited=true`, both dimensions null.
    Pin so the frontend banner can rely on `unlimited` to short-circuit
    rendering instead of having to interpret null percents itself."""
    # Pre-program the SELECT to return a Result whose `.first()` is None —
    # the "no quota row" shape from the LEFT JOIN. FakeAsyncSession's
    # default execute mock doesn't set `.first()`, so without this the
    # route's `if row is None:` short-circuit never fires and the
    # MagicMock attributes TypeError on `<=` comparison.
    no_row_result = MagicMock()
    no_row_result.first.return_value = None
    fake_db.set_execute_result(no_row_result)

    res = await client.get("/api/v1/codeguard/quota")
    assert res.status_code == 200
    body = res.json()["data"]
    assert body["unlimited"] is True
    assert body["input"] is None
    assert body["output"] is None
    assert body["organization_id"] == str(fake_auth.organization_id)


async def test_quota_route_returns_per_dimension_percent_when_quota_set(client, fake_db, fake_auth):
    """Org with a quota row → both dimensions populated with usage,
    limit, and computed percent. Frontend uses the percent for the
    progress-bar fill + the yellow/red threshold checks."""
    result = MagicMock()
    result.first.return_value = MagicMock(
        in_lim=1_000_000,
        out_lim=200_000,
        in_used=500_000,
        out_used=160_000,
        period_start=__import__("datetime").date(2026, 5, 1),
    )
    fake_db.set_execute_result(result)

    res = await client.get("/api/v1/codeguard/quota")
    assert res.status_code == 200
    body = res.json()["data"]
    assert body["unlimited"] is False
    assert body["input"] == {"used": 500_000, "limit": 1_000_000, "percent": 50.0}
    assert body["output"] == {"used": 160_000, "limit": 200_000, "percent": 80.0}
    assert body["period_start"] == "2026-05-01"


async def test_quota_route_handles_null_dimension_limit(client, fake_db):
    """One dimension NULL (unlimited on that axis) → that dimension's
    `percent` is null, the other dimension's percent computed normally."""
    result = MagicMock()
    result.first.return_value = MagicMock(
        in_lim=None,  # input unlimited
        out_lim=200_000,
        in_used=999_999,  # huge, but no cap
        out_used=50_000,
        period_start=__import__("datetime").date(2026, 5, 1),
    )
    fake_db.set_execute_result(result)

    res = await client.get("/api/v1/codeguard/quota")
    body = res.json()["data"]
    assert body["input"]["limit"] is None
    assert body["input"]["percent"] is None
    assert body["output"]["percent"] == 25.0


# ---------- GET /quota/history -----------------------------------------


async def test_quota_history_returns_recent_months_with_caps(client, fake_db, fake_auth):
    """Standard happy path. Two execute calls in order:
      1. SELECT from `codeguard_org_usage` → list of period rows.
      2. SELECT from `codeguard_org_quotas` → quota row for the caps.
    The route surfaces both so the frontend can render bars proportional
    to the configured cap (the "is 800k a lot?" question).
    """
    import datetime as _dt

    history_rows = MagicMock()
    history_rows.all.return_value = [
        MagicMock(
            period_start=_dt.date(2026, 5, 1),
            input_tokens=200_000,
            output_tokens=50_000,
        ),
        MagicMock(
            period_start=_dt.date(2026, 4, 1),
            input_tokens=800_000,
            output_tokens=150_000,
        ),
    ]
    quota_row = MagicMock()
    quota_row.first.return_value = MagicMock(in_lim=1_000_000, out_lim=200_000)
    fake_db.set_execute_result(history_rows)
    fake_db.set_execute_result(quota_row)

    res = await client.get("/api/v1/codeguard/quota/history")
    assert res.status_code == 200
    body = res.json()["data"]
    assert body["organization_id"] == str(fake_auth.organization_id)
    assert body["months"] == 3  # default
    assert body["input_limit"] == 1_000_000
    assert body["output_limit"] == 200_000
    # Most-recent first; matches the SQL `ORDER BY period_start DESC`.
    assert body["history"][0] == {
        "period_start": "2026-05-01",
        "input_tokens": 200_000,
        "output_tokens": 50_000,
    }
    assert body["history"][1]["period_start"] == "2026-04-01"


async def test_quota_history_clamps_months_to_12(client, fake_db):
    """`months=10000` from a malformed UI shouldn't trigger a tenant-bounded
    full-table scan. Pin the clamp at 12 (the route's documented ceiling)."""
    history_rows = MagicMock()
    history_rows.all.return_value = []
    quota_row = MagicMock()
    quota_row.first.return_value = None
    fake_db.set_execute_result(history_rows)
    fake_db.set_execute_result(quota_row)

    res = await client.get("/api/v1/codeguard/quota/history?months=10000")
    body = res.json()["data"]
    assert body["months"] == 12, (
        "months should clamp at 12; the page is a dashboard widget, not a "
        "billing report. A higher ceiling means a single bad URL can scan "
        "the whole tenant's usage history."
    )


async def test_quota_history_clamps_months_to_at_least_1(client, fake_db):
    """`months=0` would render an empty strip with no signal about why.
    Clamp to 1 so the response is at least the current month."""
    history_rows = MagicMock()
    history_rows.all.return_value = []
    quota_row = MagicMock()
    quota_row.first.return_value = None
    fake_db.set_execute_result(history_rows)
    fake_db.set_execute_result(quota_row)

    res = await client.get("/api/v1/codeguard/quota/history?months=0")
    assert res.json()["data"]["months"] == 1


async def test_quota_history_returns_null_caps_when_no_quota_row(client, fake_db):
    """Unlimited org (no quota row) → caps come back as null. The page
    still renders the history strip without scaling-to-cap (the "no
    cap" branch of HistoryBars)."""
    history_rows = MagicMock()
    history_rows.all.return_value = []
    quota_row = MagicMock()
    quota_row.first.return_value = None
    fake_db.set_execute_result(history_rows)
    fake_db.set_execute_result(quota_row)

    res = await client.get("/api/v1/codeguard/quota/history?months=3")
    body = res.json()["data"]
    assert body["input_limit"] is None
    assert body["output_limit"] is None
    assert body["history"] == []
