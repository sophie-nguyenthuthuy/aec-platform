"""Pin the BEHAVIOURAL contract of `services.cron_telemetry` —
beyond the surface (signatures, table shape) covered by the
existing pin file.

Three invariants this file guards that the surface pin doesn't:

  * **`cron_telemetry_wrap` MUST re-raise after recording failure.**
    arq's retry policy and error logging both depend on the
    exception propagating. A regression that swallowed the raise
    would silently mark the cron as "completed" from arq's
    perspective — no retry, no error log, no on-call alert. The
    `cron_runs` row would still say `status="failed"`, but the
    only place that signal surfaces is the dashboard. By the time
    ops opens the dashboard, the cron has missed its window.

  * **Every cron in `WorkerSettings.cron_jobs` MUST be wrapped.**
    Adding a new cron without `_telemetry(...)` means no row is
    written to `cron_runs`, the dashboard's "last_run" column
    silently reads null forever for that cron, and ops loses the
    ability to triage. The wrap is opt-in by syntax — easy to
    forget on the next addition. Pin via source-grep so the
    forgetting fails CI.

  * **Wrapped function preserves __qualname__ + signature.** arq
    inspects the signature when scheduling; a regression that
    didn't preserve it would either pass differently-named kwargs
    OR cause arq to fall back to duck-typing in unpredictable ways.

  * **`_record_finish` writes both the `succeeded` AND `failed`
    branches via the same UPDATE.** The succeeded branch is the
    happy path most ops never look at; a regression that fired
    the start INSERT but skipped the finish UPDATE would leave
    every successfully-completed cron stuck in `running` status
    — the dashboard's "Currently running" view would explode
    with false positives.

This file is read-only — exercises the wrapper against synthetic
coroutines with a stubbed `_record_start` / `_record_finish` so
no DB is needed. Survives reverts.
"""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from uuid import uuid4

import pytest

# ---------- Re-raise behaviour ----------


@pytest.fixture
def stubbed_telemetry_io(monkeypatch):
    """Stub `_record_start` / `_record_finish` so the wrapper runs
    without needing a real DB. Captures finish-writes so we can
    assert the status, duration, and error_message branches."""
    from services import cron_telemetry as ct

    finish_calls: list[dict] = []

    async def _stub_start(cron_name: str):
        return uuid4()

    async def _stub_finish(run_id, *, status, duration_ms, error_message):
        finish_calls.append(
            {
                "run_id": run_id,
                "status": status,
                "duration_ms": duration_ms,
                "error_message": error_message,
            }
        )

    monkeypatch.setattr(ct, "_record_start", _stub_start)
    monkeypatch.setattr(ct, "_record_finish", _stub_finish)
    return finish_calls


def test_wrap_reraises_on_inner_exception(stubbed_telemetry_io):
    """SECURITY/CORRECTNESS pin. The wrapped cron raises a synthetic
    exception. The wrapper MUST re-raise so arq sees the error.
    A regression that swallowed it would silently break:
      * arq's retry policy (no retry on swallow)
      * arq's error log (no log line on swallow)
      * on-call paging (no exception, no Sentry capture)
    """
    from services.cron_telemetry import cron_telemetry_wrap

    async def failing_cron(ctx):
        raise RuntimeError("synthetic failure")

    wrapped = cron_telemetry_wrap(failing_cron)

    with pytest.raises(RuntimeError, match="synthetic failure"):
        asyncio.run(wrapped({}))

    # AND it MUST have written a `failed` row before re-raising.
    assert len(stubbed_telemetry_io) == 1, (
        f"Expected exactly one finish write; got {len(stubbed_telemetry_io)}. "
        "The wrapper either skipped the failure-record path OR called "
        "_record_finish twice."
    )
    finish = stubbed_telemetry_io[0]
    assert finish["status"] == "failed", (
        f"Wrapper recorded status={finish['status']!r} on a failed run; "
        "want 'failed'. Dashboard's failure-rate metric depends on this string."
    )
    assert finish["error_message"] is not None
    assert "RuntimeError" in finish["error_message"]
    assert "synthetic failure" in finish["error_message"]
    # Duration is captured even on the failure branch (operators
    # care: "did it fail fast or slow?").
    assert finish["duration_ms"] is not None
    assert finish["duration_ms"] >= 0


def test_wrap_records_succeeded_on_clean_return(stubbed_telemetry_io):
    """Happy path. The wrapper MUST write the `succeeded` finish
    record AND return the original coroutine's return value
    unchanged."""
    from services.cron_telemetry import cron_telemetry_wrap

    async def ok_cron(ctx):
        return {"summary": "ok"}

    wrapped = cron_telemetry_wrap(ok_cron)

    out = asyncio.run(wrapped({}))
    assert out == {"summary": "ok"}, (
        f"Wrapped cron's return value was altered: {out!r}. The wrapper "
        "MUST be transparent on success — callers depend on the original "
        "return shape."
    )

    assert len(stubbed_telemetry_io) == 1
    finish = stubbed_telemetry_io[0]
    assert finish["status"] == "succeeded"
    assert finish["error_message"] is None
    assert finish["duration_ms"] is not None and finish["duration_ms"] >= 0


def test_wrap_handles_record_start_failure_gracefully(monkeypatch):
    """Defensive: if `_record_start` returns None (DB outage), the
    wrapper MUST still run the cron body. Telemetry is best-effort —
    losing a row of telemetry is far better than skipping a real
    cron run because the telemetry DB is down.

    We pin this because the failure mode is silent — without it,
    a transient DB blip during a cron's start would silently skip
    the cron entirely.
    """
    from services import cron_telemetry as ct

    async def _stub_start_returns_none(cron_name: str):
        return None  # simulates DB outage

    finish_calls: list[dict] = []

    async def _stub_finish(*args, **kwargs):
        finish_calls.append(kwargs)

    monkeypatch.setattr(ct, "_record_start", _stub_start_returns_none)
    monkeypatch.setattr(ct, "_record_finish", _stub_finish)

    cron_ran = {"value": False}

    async def my_cron(ctx):
        cron_ran["value"] = True
        return "result"

    wrapped = ct.cron_telemetry_wrap(my_cron)
    out = asyncio.run(wrapped({}))

    assert cron_ran["value"] is True, (
        "Wrapper skipped the cron body when _record_start returned None. Telemetry blips MUST NOT skip real work."
    )
    assert out == "result"
    # And `_record_finish` MUST NOT be called (no run_id to update).
    assert finish_calls == []


# ---------- workers/queue.py wiring ----------


def test_every_cron_in_queue_uses_telemetry_wrap():
    """SOURCE-GREP pin: every `cron(...)` call in `workers/queue.py`
    MUST have its first argument wrapped via `_telemetry(...)`. The
    forget-to-wrap-on-new-cron is a real-world failure mode (low
    cognitive cost to add a cron line, easy to forget the wrap),
    and the silent failure ("dashboard's last_run is null forever
    for this cron") gives no signal.

    Pin by inspecting the source: every `cron(` call should be
    immediately followed by `_telemetry(`. If a future regression
    breaks this, CI fails before the silent telemetry loss reaches
    prod.
    """
    queue_path = Path(__file__).parent.parent / "workers" / "queue.py"
    src = queue_path.read_text()

    import re

    # Find every `cron(...)` call inside a list literal context. The
    # `cron(` followed by anything that doesn't start with `_telemetry`
    # would indicate a missed wrap.
    cron_calls = re.findall(r"\bcron\(([^,)]+)", src)

    # Filter to ones that look like cron-job declarations (first arg
    # is an identifier, not a string or further function call).
    misses: list[str] = []
    for first_arg in cron_calls:
        first_arg = first_arg.strip()
        # Skip the import line `from arq.cron import cron` etc.
        if not first_arg or first_arg.startswith(("'", '"')):
            continue
        # The first arg MUST start with `_telemetry(` to be wrapped.
        if not first_arg.startswith("_telemetry("):
            misses.append(first_arg)

    assert not misses, (
        f"workers/queue.py has cron(...) calls whose first argument "
        f"is NOT wrapped via _telemetry(): {misses}. Adding a cron "
        "without the wrapper means no row in `cron_runs` ever gets "
        "written for that cron — the dashboard's last_run column "
        "is silently null for that cron forever. Wrap with "
        "`_telemetry(...)` at the cron declaration site."
    )


def test_workers_queue_imports_telemetry_wrap():
    """The wrapper MUST be imported as `_telemetry` (the convention
    used across every cron declaration). A regression that renamed
    or dropped the import would either fail import-time loudly OR
    silently leave the per-cron call unwrapped if a future cron
    used a different alias."""
    queue_path = Path(__file__).parent.parent / "workers" / "queue.py"
    src = queue_path.read_text()

    assert "from services.cron_telemetry import cron_telemetry_wrap as _telemetry" in src, (
        "workers/queue.py no longer imports cron_telemetry_wrap as `_telemetry`. "
        "Every cron declaration uses this alias; a rename has to move "
        "every call site in lockstep."
    )


# ---------- Signature preservation ----------


def test_wrap_preserves_signature():
    """arq inspects the signature when registering the cron. A
    regression that dropped `__signature__` preservation would let
    arq fall back to duck-typing — which works for the simple
    `(ctx)` case but breaks if a cron ever takes typed kwargs."""
    from services.cron_telemetry import cron_telemetry_wrap

    async def example_cron(ctx: dict, *, custom_arg: str = "default") -> int:
        return 0

    wrapped = cron_telemetry_wrap(example_cron)

    # The wrapper attaches __signature__ explicitly so
    # `inspect.signature(wrapped)` returns the original's params.
    wrapped_sig = inspect.signature(wrapped)
    original_sig = inspect.signature(example_cron)

    assert list(wrapped_sig.parameters.keys()) == list(original_sig.parameters.keys()), (
        f"cron_telemetry_wrap dropped signature info: "
        f"wrapped has {list(wrapped_sig.parameters.keys())}, "
        f"original has {list(original_sig.parameters.keys())}."
    )
