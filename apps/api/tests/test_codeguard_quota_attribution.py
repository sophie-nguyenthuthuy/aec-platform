"""Unit tests for `services/codeguard_quota_attribution.py`.

The simple write-side helpers (`record_user_usage`,
`record_user_usage_by_route`, `route_weight_for`) are covered in
`test_codeguard_quotas.py`. THIS file pins the harder-to-cover
contracts:

  1. `_apply_weight` edge cases — banker's rounding direction,
     negative-weight clamp, zero-weight short-circuit.
  2. `with_usage_recording` orchestration — that all THREE writes
     fire on success (org + user + per-route), that the threshold
     check fires AFTER the writes, that a failure on any one write
     doesn't roll back the others.

Tier 1 (mocked) — no live DB. Pinning at this layer because the
context manager is called from every codeguard route handler;
silent regressions in its drain/notify ordering would corrupt cap
state across the entire surface.
"""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

pytestmark = pytest.mark.asyncio


# ---------- _apply_weight edge cases --------------------------------------


def test_apply_weight_rounds_half_to_even_not_truncates():
    """Python's `round()` uses banker's rounding (half-to-even). Pin
    the direction explicitly: `333 * 1.5 = 499.5` rounds to 500
    (.5 → even = 500), NOT 499 (truncation). Truncation would bias
    weighted routes ~0.5 tokens/call low — millions of requests/month
    accumulate that bias."""
    from services.codeguard_quota_attribution import _apply_weight

    # 333 * 1.5 = 499.5 → 500 (banker's: round half to even, 500 is even)
    assert _apply_weight(333, 1.5) == 500
    # 1000 * 1.5 = 1500 — exact, no rounding ambiguity
    assert _apply_weight(1000, 1.5) == 1500


def test_apply_weight_clamps_negative_to_zero():
    """Negative weights are operator typos — clamp to 0 rather than
    silently REDUCE recorded usage (which would breach the cap
    quietly on every weighted call)."""
    from services.codeguard_quota_attribution import _apply_weight

    assert _apply_weight(1000, -1.0) == 0
    assert _apply_weight(1000, -5.0) == 0


def test_apply_weight_zero_returns_zero():
    """Zero weight is a valid configuration ("this route is free") —
    returns 0 explicitly, not via the negative-clamp path. Pin so a
    refactor of the clamp logic doesn't change the boundary
    behavior."""
    from services.codeguard_quota_attribution import _apply_weight

    assert _apply_weight(1000, 0.0) == 0


def test_apply_weight_unity_is_identity():
    """The default weight (1.0) MUST be the identity transform —
    otherwise every unweighted route accumulates rounding error.
    Pin the boundary."""
    from services.codeguard_quota_attribution import _apply_weight

    for tokens in (0, 1, 100, 1_000_000, 2**31):
        assert _apply_weight(tokens, 1.0) == tokens


# ---------- with_usage_recording orchestration ----------------------------


def _stub_telemetry(monkeypatch, seed_input: int = 0, seed_output: int = 0):
    """Stub `ml.pipelines.codeguard.{set,clear}_telemetry_accumulator`
    so the test seeds the accumulator with non-zero counts. The real
    pipeline populates these via `_record_llm_call`'s on_llm_end
    hook; here we bypass and seed directly to drive the drain path."""

    class _AccStub:
        input_tokens = seed_input
        output_tokens = seed_output

    def _set_acc(_acc):
        return None

    def _clear_acc(_token):
        return None

    # Re-import-friendly: patch on the actual module.
    import ml.pipelines.codeguard as cg_pipeline

    monkeypatch.setattr(cg_pipeline, "TelemetryAccumulator", _AccStub)
    monkeypatch.setattr(cg_pipeline, "set_telemetry_accumulator", _set_acc)
    monkeypatch.setattr(cg_pipeline, "clear_telemetry_accumulator", _clear_acc)


async def test_with_usage_recording_skips_all_writes_on_zero_acc(monkeypatch):
    """HyDE cache hit → accumulator stays at (0, 0). All three record
    fns AND the threshold check should be skipped — no DB load for
    free requests. Pin so a refactor that moves the zero-skip out of
    the helper doesn't accidentally start writing zero rows."""
    from services.codeguard_quota_attribution import with_usage_recording

    _stub_telemetry(monkeypatch, seed_input=0, seed_output=0)

    org_writes: list = []
    user_writes: list = []
    by_route_writes: list = []
    notify_calls: list = []

    async def _record_org(_db, _org, **kw):
        org_writes.append(kw)

    async def _record_user(_db, _org, _user, **kw):
        user_writes.append(kw)

    async def _record_by_route(_db, _org, _user, **kw):
        by_route_writes.append(kw)

    async def _notify(_db, _org):
        notify_calls.append(_org)

    monkeypatch.setattr("services.codeguard_quotas.record_org_usage", _record_org)
    monkeypatch.setattr("services.codeguard_quota_attribution.record_user_usage", _record_user)
    monkeypatch.setattr(
        "services.codeguard_quota_attribution.record_user_usage_by_route",
        _record_by_route,
    )
    monkeypatch.setattr("services.codeguard_quotas.check_and_notify_thresholds", _notify)

    auth = MagicMock()
    auth.organization_id = uuid4()
    auth.user_id = uuid4()
    db = MagicMock()

    async with with_usage_recording(db, auth, route_key="query"):
        pass  # accumulator stays at zeros

    # Zero-acc path: NONE of the writes fire. Threshold check also
    # skips (the percent didn't change).
    assert org_writes == []
    assert user_writes == []
    assert by_route_writes == []
    assert notify_calls == []


async def test_with_usage_recording_fires_all_three_writes_on_success(monkeypatch):
    """Non-zero acc → all three writes (org + user + per-route) AND
    the threshold check. Pin so a refactor doesn't accidentally drop
    one of the three sidecars (which the previous reverter pattern
    has done before)."""
    from services.codeguard_quota_attribution import with_usage_recording

    _stub_telemetry(monkeypatch, seed_input=1000, seed_output=200)

    org_writes: list = []
    user_writes: list = []
    by_route_writes: list = []
    notify_calls: list = []

    async def _record_org(_db, _org, **kw):
        org_writes.append(kw)

    async def _record_user(_db, _org, _user, **kw):
        user_writes.append(kw)

    async def _record_by_route(_db, _org, _user, **kw):
        by_route_writes.append(kw)

    async def _notify(_db, _org):
        notify_calls.append(_org)

    monkeypatch.setattr("services.codeguard_quotas.record_org_usage", _record_org)
    monkeypatch.setattr("services.codeguard_quota_attribution.record_user_usage", _record_user)
    monkeypatch.setattr(
        "services.codeguard_quota_attribution.record_user_usage_by_route",
        _record_by_route,
    )
    monkeypatch.setattr("services.codeguard_quotas.check_and_notify_thresholds", _notify)

    auth = MagicMock()
    auth.organization_id = uuid4()
    auth.user_id = uuid4()
    db = MagicMock()

    async with with_usage_recording(db, auth, route_key="scan"):
        pass

    assert len(org_writes) == 1
    assert len(user_writes) == 1
    assert len(by_route_writes) == 1
    assert len(notify_calls) == 1, (
        "Threshold-notification check must fire AFTER the usage write — "
        "otherwise the percent reads pre-increment values and 80%/95% "
        "crossings get missed."
    )

    # The /scan route weight (5×) flows through to BOTH user-level
    # writes — pin that the pre-weighting in the helper applies to
    # the org-level write (which doesn't take route_weight as a
    # kwarg) by inspecting the org write's bound tokens.
    assert org_writes[0]["input_tokens"] == 5000  # 1000 × 5
    assert org_writes[0]["output_tokens"] == 1000  # 200 × 5
    # User-level writes carry the weight as a kwarg.
    assert user_writes[0]["route_weight"] == 5.0
    assert by_route_writes[0]["route_weight"] == 5.0
    assert by_route_writes[0]["route_key"] == "scan"


async def test_with_usage_recording_org_failure_does_not_block_user_writes(monkeypatch):
    """The org-level write is load-bearing for cap checks. If it
    fails (transient DB blip), the user-level writes MUST still fire
    so the per-user attribution stays consistent — the reconcile cron
    will catch divergence between org and user sums anyway, and
    skipping the user write here would mean two failure modes for
    one transient blip."""
    from services.codeguard_quota_attribution import with_usage_recording

    _stub_telemetry(monkeypatch, seed_input=1000, seed_output=200)

    user_writes: list = []
    by_route_writes: list = []

    async def _record_org_fails(_db, _org, **kw):
        raise RuntimeError("simulated transient DB error")

    async def _record_user(_db, _org, _user, **kw):
        user_writes.append(kw)

    async def _record_by_route(_db, _org, _user, **kw):
        by_route_writes.append(kw)

    async def _notify(_db, _org):
        return None

    monkeypatch.setattr("services.codeguard_quotas.record_org_usage", _record_org_fails)
    monkeypatch.setattr("services.codeguard_quota_attribution.record_user_usage", _record_user)
    monkeypatch.setattr(
        "services.codeguard_quota_attribution.record_user_usage_by_route",
        _record_by_route,
    )
    monkeypatch.setattr("services.codeguard_quotas.check_and_notify_thresholds", _notify)

    auth = MagicMock()
    auth.organization_id = uuid4()
    auth.user_id = uuid4()
    db = MagicMock()

    # Should NOT raise — the org failure is logged + swallowed.
    async with with_usage_recording(db, auth, route_key="query"):
        pass

    # User-level writes proceeded despite the org-level failure.
    assert len(user_writes) == 1
    assert len(by_route_writes) == 1


async def test_with_usage_recording_user_failure_does_not_propagate(monkeypatch):
    """The per-user write is a sidecar — its failure must NOT bubble
    up to the request handler. The request has already been served;
    raising here would 502 a successful LLM call. Pin the swallow."""
    from services.codeguard_quota_attribution import with_usage_recording

    _stub_telemetry(monkeypatch, seed_input=1000, seed_output=200)

    org_writes: list = []
    notify_calls: list = []

    async def _record_org(_db, _org, **kw):
        org_writes.append(kw)

    async def _record_user_fails(_db, _org, _user, **kw):
        raise RuntimeError("simulated transient FK error")

    async def _record_by_route_fails(_db, _org, _user, **kw):
        raise RuntimeError("simulated transient FK error")

    async def _notify(_db, _org):
        notify_calls.append(_org)

    monkeypatch.setattr("services.codeguard_quotas.record_org_usage", _record_org)
    monkeypatch.setattr(
        "services.codeguard_quota_attribution.record_user_usage",
        _record_user_fails,
    )
    monkeypatch.setattr(
        "services.codeguard_quota_attribution.record_user_usage_by_route",
        _record_by_route_fails,
    )
    monkeypatch.setattr("services.codeguard_quotas.check_and_notify_thresholds", _notify)

    auth = MagicMock()
    auth.organization_id = uuid4()
    auth.user_id = uuid4()
    db = MagicMock()

    # Should NOT raise — both sidecar failures are swallowed.
    async with with_usage_recording(db, auth, route_key="query"):
        pass

    # Org-level write succeeded.
    assert len(org_writes) == 1
    # Threshold check still fires — the org write is what unblocks it,
    # and that succeeded. Per-user attribution being stale doesn't
    # affect threshold notifications (they read org_usage).
    assert len(notify_calls) == 1


async def test_with_usage_recording_yields_accumulator_for_inspection(monkeypatch):
    """The context manager YIELDs the accumulator so handlers can
    inspect mid-flight token counts (e.g. for SSE streams that want
    to mid-stream cap-check). Pin the yield contract — a refactor
    that yields nothing breaks every streaming route."""
    from services.codeguard_quota_attribution import with_usage_recording

    _stub_telemetry(monkeypatch, seed_input=42, seed_output=7)

    async def _noop(*_a, **_kw):
        return None

    monkeypatch.setattr("services.codeguard_quotas.record_org_usage", _noop)
    monkeypatch.setattr("services.codeguard_quota_attribution.record_user_usage", _noop)
    monkeypatch.setattr("services.codeguard_quota_attribution.record_user_usage_by_route", _noop)
    monkeypatch.setattr("services.codeguard_quotas.check_and_notify_thresholds", _noop)

    auth = MagicMock()
    auth.organization_id = uuid4()
    auth.user_id = uuid4()
    db = MagicMock()

    async with with_usage_recording(db, auth, route_key="query") as acc:
        # The yielded accumulator carries the seeded counts so a
        # streaming handler can read them mid-flight.
        assert acc.input_tokens == 42
        assert acc.output_tokens == 7
