"""Database connection leak detector — opt-in fixture + self-test.

The bug class
-------------
A test calls something like:

    async def test_foo():
        session = await some_factory()
        await session.execute(...)
        # forgot `await session.close()` OR an early-return short-circuited it

The session lives forever — pinned in the asyncpg pool until the
test process exits. On a single test, no symptom. Across hundreds of
tests on a slow CI machine, the pool exhausts mid-run and you see
"too many connections" errors with no clean repro (the failing test
isn't the leaky one — it's the next test downstream).

Runtime tests don't catch this. Coverage doesn't see it. Even
`asyncio.all_tasks()` at end-of-test doesn't surface it because
the session might be in a "closed but not garbage-collected" state.

What this module provides
-------------------------
1. `TrackedSessionFactory` — a wrapper around any
   `async_sessionmaker` that increments a live-session counter on
   enter and decrements on exit. Exposes `.live_count` (current)
   and `.peak_count` (high-water-mark for the test).

2. `assert_no_leaked_sessions(factory, *, name)` — a teardown
   helper. Pin in your test's fixture to assert all sessions
   opened during the test were closed before teardown.

3. Self-tests below verify the detector itself works — without
   them a bug in the wrapper would silently let leaks through.

Why a wrapper, not a global asyncpg patch
-----------------------------------------
Patching the asyncpg pool globally would catch every session in
the test process, including ones the framework opens for its own
bookkeeping (alembic, the FastAPI startup hook). Filtering noise
out of those would force per-test exemption rules. A wrapper that
operates only on the factory tests opt INTO is precise — the
handful of leaks it catches are real handler bugs, not framework
plumbing.

Usage in integration tests:

    @pytest.fixture
    async def tracked_engine():
        engine = create_async_engine(URL)
        factory = TrackedSessionFactory(
            async_sessionmaker(engine, class_=AsyncSession)
        )
        yield factory
        assert_no_leaked_sessions(factory, name="my_integration_test")
        await engine.dispose()

The integration lane is where real connection leaks matter (unit-
lane FakeAsyncSession is a no-op). Wiring this into specific
integration suites is incremental; this module just provides the
machinery.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest


class TrackedSessionFactory:
    """Wraps an async session factory to track open/close lifecycle.

    The wrapped factory is anything callable that returns an
    async-context-manager session — `async_sessionmaker(...)` from
    SQLAlchemy is the standard case, but the wrapper is duck-typed
    so a test fake works too.

    Counters:
      * `live_count` — currently-open sessions. Should be 0 at
        test teardown unless the test legitimately holds one open
        across phases.
      * `peak_count` — high-water-mark across the test's lifetime.
        Useful for asserting "this endpoint never opens more than
        N concurrent sessions."
      * `total_opened` — cumulative count. Lets you assert
        end-state "exactly N sessions were opened during this test."
    """

    def __init__(self, inner_factory: Any) -> None:
        self._inner = inner_factory
        self.live_count = 0
        self.peak_count = 0
        self.total_opened = 0
        # Track each open session so a debug dump at teardown can
        # name which ones leaked. We use id() rather than the session
        # itself so we don't pin them in memory past their natural
        # lifetime.
        self._live_ids: set[int] = set()

    def __call__(self) -> _TrackedSessionContext:
        """Return an async context manager that wraps a fresh session.

        The wrapper increments on `__aenter__` and decrements on
        `__aexit__` — matches the standard `async with factory() as s`
        usage.
        """
        return _TrackedSessionContext(self)


class _TrackedSessionContext:
    """Async context manager wrapping a session from the inner factory."""

    def __init__(self, factory: TrackedSessionFactory) -> None:
        self._factory = factory
        self._session: Any = None
        self._inner_cm: Any = None
        self._sid: int = 0

    async def __aenter__(self) -> Any:
        # The inner factory may itself be either sync (returns an
        # async-context-manager) or async (returns an awaitable that
        # resolves to a session). Try the standard sync-factory shape
        # first — async_sessionmaker is sync.
        cm = self._factory._inner()
        # `cm` is the async-context-manager; entering it gives the
        # session.
        self._inner_cm = cm
        self._session = await cm.__aenter__()
        self._factory.live_count += 1
        self._factory.total_opened += 1
        if self._factory.live_count > self._factory.peak_count:
            self._factory.peak_count = self._factory.live_count
        self._sid = id(self._session)
        self._factory._live_ids.add(self._sid)
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> bool | None:
        try:
            return await self._inner_cm.__aexit__(exc_type, exc, tb)
        finally:
            # Decrement even if the inner __aexit__ raised — a session
            # that errors during close STILL released the connection
            # to the pool (asyncpg's behaviour); under-counting would
            # report false-positive leaks.
            self._factory.live_count -= 1
            self._factory._live_ids.discard(self._sid)


def assert_no_leaked_sessions(factory: TrackedSessionFactory, *, name: str) -> None:
    """Teardown assertion: every session opened during the test
    has been closed.

    `name` shows up in the failure message — surface the
    test/fixture/suite name so the offender is unambiguous.
    """
    if factory.live_count != 0:
        raise AssertionError(
            f"{factory.live_count} session(s) leaked at end of {name!r} "
            f"(total opened: {factory.total_opened}, peak: "
            f"{factory.peak_count}).\n\n"
            "A test or its fixture opened sessions and never closed them. "
            "Common shapes:\n"
            "  • `s = factory()` (no `async with`) — the context manager "
            "never runs `__aexit__`.\n"
            "  • An early `return` / `raise` inside the `async with` — "
            "Python DOES run `__aexit__` here, but if you stored the "
            "session in a class attribute and overwrote it, the prior "
            "one leaks.\n"
            "  • A test that yields a session via a generator-fixture "
            "and never advances past the yield (e.g. a downstream test "
            "raised before the cleanup code).\n\n"
            "Run with `-vv` to see which test in the suite leaked — "
            "the offender is usually the one whose teardown failed last."
        )


# ---------- Self-tests ----------
#
# These verify the detector itself works. Without them, a regression
# in `_TrackedSessionContext` would silently let leaks through and
# every consumer of this module would gain false confidence.


@asynccontextmanager
async def _fake_session() -> AsyncIterator[dict]:
    """Stand-in for `async_sessionmaker(...)()`. Yields a plain dict
    so tests can poke at the object identity to confirm the wrapper
    forwards the same instance through `__aenter__`."""
    yield {"_marker": "session"}


def _fake_factory() -> Any:
    """Acts like `async_sessionmaker(...)` — calling it returns a
    fresh session async-context-manager."""
    return _fake_session()


pytestmark = pytest.mark.asyncio


async def test_factory_increments_then_decrements_around_session():
    """Happy path: enter + exit balances the counter back to 0."""
    f = TrackedSessionFactory(_fake_factory)

    assert f.live_count == 0
    assert f.total_opened == 0

    async with f() as s:
        assert s["_marker"] == "session"
        assert f.live_count == 1
        assert f.total_opened == 1
        assert f.peak_count == 1

    assert f.live_count == 0
    assert f.total_opened == 1  # cumulative; doesn't reset
    assert f.peak_count == 1


async def test_factory_tracks_concurrent_sessions():
    """Two sessions open at once — peak should hit 2; live should
    decrement back to 0 after both close."""
    f = TrackedSessionFactory(_fake_factory)

    cm1 = f()
    cm2 = f()
    s1 = await cm1.__aenter__()
    assert f.live_count == 1
    s2 = await cm2.__aenter__()
    assert f.live_count == 2
    assert f.peak_count == 2

    await cm1.__aexit__(None, None, None)
    assert f.live_count == 1
    await cm2.__aexit__(None, None, None)
    assert f.live_count == 0

    assert f.total_opened == 2
    assert f.peak_count == 2

    # Sanity: the two sessions are different instances; the wrapper
    # didn't accidentally reuse one.
    assert s1 is not s2


async def test_factory_decrements_even_when_inner_aexit_raises():
    """A close that raises must STILL drop the live counter — the
    connection is back in the pool regardless of whether the
    cleanup code errored.
    """

    @asynccontextmanager
    async def _raising_session() -> AsyncIterator[dict]:
        try:
            yield {"_marker": "session"}
        finally:
            raise RuntimeError("simulated close failure")

    f = TrackedSessionFactory(_raising_session)
    with pytest.raises(RuntimeError, match="close failure"):
        async with f():
            assert f.live_count == 1
    # Despite the error, live_count is back to 0.
    assert f.live_count == 0


async def test_assert_no_leaked_sessions_passes_clean_factory():
    """Helper passes when nothing leaked."""
    f = TrackedSessionFactory(_fake_factory)
    async with f():
        pass
    assert_no_leaked_sessions(f, name="self-test/clean")  # no raise


async def test_assert_no_leaked_sessions_raises_on_actual_leak():
    """Helper raises with a useful message when sessions leak.

    This is the gate the integration suites depend on. A regression
    that quietly returned without raising would silently let real
    leaks through.
    """
    f = TrackedSessionFactory(_fake_factory)
    cm = f()
    await cm.__aenter__()
    # Simulate a test that exits without closing the session.
    assert f.live_count == 1
    with pytest.raises(AssertionError, match="leaked at end"):
        assert_no_leaked_sessions(f, name="self-test/leak")
    # Cleanup so we don't pollute the test process.
    await cm.__aexit__(None, None, None)


async def test_factory_total_opened_is_cumulative_across_sessions():
    """`total_opened` increments per-open and never decrements —
    even after sessions close.

    Pin this so an "improvement" that resets it on close (which
    would lose the historical count) can't ship without the test
    failing first.
    """
    f = TrackedSessionFactory(_fake_factory)
    for _ in range(5):
        async with f():
            pass
    assert f.live_count == 0
    assert f.total_opened == 5
    assert f.peak_count == 1  # never more than 1 concurrent
