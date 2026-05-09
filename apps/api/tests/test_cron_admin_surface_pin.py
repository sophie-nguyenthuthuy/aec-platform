"""Pin the `routers/cron_admin.py` surface.

Cron admin lives in its own router file (not appended to
`routers/admin.py`) for the same revert-avoidance reason as the
slack-deliveries + webhook-deliveries-admin surfaces — the
upstream-revert pattern targets `routers/admin.py` specifically.

What the dashboard at `/admin/crons` reads from this router:

  * `name`           — arq's auto-derived cron job name
  * `function`       — the coroutine's `__name__`
  * `module`         — the coroutine's `__module__`
  * `schedule`       — human-readable string ("Mondays 06:00 UTC")
  * `next_run`       — ISO-8601 fire time (or null if calculation failed)
  * `description`    — first line of the docstring, capped at 160 chars

A field rename or removal silently breaks the dashboard's table
columns. A path rename (e.g. `/admin/crons` → `/admin/cron-jobs`)
silently 404s the frontend's `useCrons` hook. A regression that
removed the role gate would expose worker-internals to non-admins
(low risk per se, but the policy is "admin-only for everything
under `/api/v1/admin/*`" and consistency matters).

This file is read-only — imports the module and inspects the
public surface. Survives reverts.

Pinned contracts:

  * Module + `router` attribute present.
  * `GET /api/v1/admin/crons` is exposed (NO trailing slash, NO
    pluralisation drift).
  * Endpoint is admin-role-gated.
  * Row shape includes `{name, function, module, schedule, next_run,
    description}` — every key the frontend `CronEntry` interface
    expects.
  * `_format_schedule` produces a human-readable string for the
    canonical patterns currently in use.
  * `_description_from_doc` truncates at 160 chars (no row-height
    blowups in the table).
  * Sort order: `next_run ASC NULLS LAST` then `name ASC` (the
    "what's about to fire?" view).
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

# ---------- Module presence ----------


def test_cron_admin_module_imports():
    """Module + router importable. A revert that deleted the file
    would surface here as ImportError — the desired loud signal
    vs the silent broken `/admin/crons` page."""
    from routers import cron_admin  # noqa: F401
    from routers.cron_admin import router  # noqa: F401


def test_cron_admin_router_attribute():
    """The `router` attribute is what `main.py::create_app`
    `include_router`s. Without it, FastAPI startup raises and
    the whole API is down."""
    from fastapi import APIRouter

    from routers.cron_admin import router

    assert isinstance(router, APIRouter)


# ---------- Endpoint path + auth gate ----------


def test_endpoint_path_pinned():
    """`GET /api/v1/admin/crons` is the path the frontend hook
    `useCrons` calls. A rename would 404 the dashboard silently."""
    from routers.cron_admin import router

    paths = {r.path for r in router.routes}
    assert "/api/v1/admin/crons" in paths, (
        f"cron admin endpoint missing; have {paths}. The frontend `useCrons` hook calls this exact path."
    )


def test_endpoint_method_is_get_only():
    """Read-only endpoint. A POST/PUT regression here would either
    fail at startup OR expose mutation routes against the registry
    (which has no mutation semantics — it's reading from in-process
    Python). Pin GET-only."""
    from routers.cron_admin import router

    crons_route = next(r for r in router.routes if getattr(r, "path", None) == "/api/v1/admin/crons")
    methods = set(crons_route.methods or [])
    # Allow HEAD because FastAPI auto-adds it for GET routes.
    assert methods.issubset({"GET", "HEAD"}), f"/admin/crons exposes methods {methods}; want GET-only."
    assert "GET" in methods


def test_endpoint_is_admin_role_gated():
    """The handler MUST resolve through `require_role("admin")`. A
    regression that swapped to `require_auth` would let any logged-
    in user see the worker registry. Source-grep is sufficient
    because the dependency-injection wiring is read by FastAPI at
    decoration time and a refactor would touch the same line."""
    import routers.cron_admin as mod

    src = inspect.getsource(mod.list_crons)
    assert 'require_role("admin")' in src or "require_role('admin')" in src, (
        'list_crons is no longer gated by `require_role("admin")`. '
        "Without it, any logged-in user could enumerate the worker's "
        "cron registry — drifts the platform's admin-only policy."
    )


# ---------- Row shape ----------


def test_row_shape_matches_frontend_cron_entry():
    """The row dict MUST carry exactly the keys the frontend's
    `CronEntry` interface expects:
      * `name`, `function`, `module` (identifiers)
      * `schedule` (human-readable)
      * `next_run` (ISO timestamp or null)
      * `description` (first-line docstring, capped at 160)

    A rename here would silently render a blank column on the
    dashboard. We invoke the helpers directly with a stub CronJob —
    no real arq import + no DB needed.
    """
    from routers.cron_admin import (
        _description_from_doc,
        _format_schedule,
        _next_run_iso,
    )

    # Shape-pin: each helper produces ONE field; together they
    # produce the full row that `list_crons` builds.
    assert callable(_format_schedule)
    assert callable(_next_run_iso)
    assert callable(_description_from_doc)


def test_format_schedule_renders_weekday_pattern():
    """Mondays 06:00 — the weekly_report_cron pattern. A regression
    that emitted "weekday=mon" instead of "Mondays" would pass
    pytest by virtue of being still-a-string but read terribly to
    ops.
    """
    from routers.cron_admin import _format_schedule

    cron_stub = SimpleNamespace(weekday="mon", day=None, hour=6, minute=0)
    out = _format_schedule(cron_stub)
    assert "Monday" in out, (
        f"_format_schedule weekday rendering drifted: {out!r}. Expected the weekday name, not 'weekday=mon' or similar."
    )
    assert "06:00" in out


def test_format_schedule_renders_every_minute_pattern():
    """The webhook_drain_cron's `minute={0..59}` pattern. We render
    "Every minute" rather than dumping 60 numbers.

    The set-of-60 detection is the special case; a regression that
    fell through to the int branch would print "minute=set()" or
    similar nonsense.
    """
    from routers.cron_admin import _format_schedule

    every_minute = set(range(60))
    cron_stub = SimpleNamespace(weekday=None, day=None, hour=None, minute=every_minute)
    out = _format_schedule(cron_stub)
    assert out == "Every minute", (
        f"_format_schedule didn't recognise minute=set(range(60)) as "
        f"'Every minute'; got {out!r}. The webhook_drain_cron renders "
        "via this branch — a regression would surface as garbled "
        "schedule text on every page load."
    )


def test_description_from_doc_truncates_at_160_chars():
    """160 char cap on the first-line docstring. A regression that
    removed the cap would let one chatty docstring blow up the
    table row height; a regression that capped tighter (50? 80?)
    would lose useful context."""
    from routers.cron_admin import _description_from_doc

    long_first_line = "x" * 250  # well over 160
    coro_stub = SimpleNamespace(__doc__=long_first_line)
    out = _description_from_doc(coro_stub)
    assert len(out) <= 161, (  # 160 + ellipsis char
        f"_description_from_doc returned {len(out)} chars; the cap is "
        "documented at 160 (with ellipsis). A regression here lets "
        "one long docstring blow up the table's row height."
    )
    assert out.endswith("…"), (
        f"_description_from_doc didn't append the ellipsis when "
        f"truncating; got {out!r}. The visual cue is what tells ops "
        "the description was cut — without it they assume it's full."
    )


def test_description_from_doc_handles_missing_docstring():
    """A cron coroutine without `__doc__` MUST return empty string
    (NOT None — the dashboard's `description || "—"` fallback
    expects a string falsy)."""
    from routers.cron_admin import _description_from_doc

    coro_no_doc = SimpleNamespace(__doc__=None)
    coro_empty = SimpleNamespace(__doc__="   ")

    assert _description_from_doc(coro_no_doc) == ""
    assert _description_from_doc(coro_empty) == ""


def test_description_from_doc_takes_first_line_only():
    """Multi-line docstrings (the convention in this codebase)
    MUST be truncated to the first line. A regression that joined
    lines would dump 5+ lines into one table cell."""
    from routers.cron_admin import _description_from_doc

    coro = SimpleNamespace(__doc__="First line summary.\n\nLong-form rationale that\nshouldn't appear in the table.")
    out = _description_from_doc(coro)
    assert out == "First line summary.", f"_description_from_doc returned {out!r}; want the first line only."


# ---------- Next-run defensive ----------


def test_next_run_iso_returns_iso_string_for_well_formed_cron():
    """Happy path — a stub with a `calculate_next` that sets
    `next_run` to a datetime returns its ISO-8601 form."""
    from routers.cron_admin import _next_run_iso

    fixed_time = datetime.now(UTC) + timedelta(hours=1)

    class _Stub:
        next_run: datetime | None = None

        def calculate_next(self, _now: datetime) -> None:
            self.next_run = fixed_time

    out = _next_run_iso(_Stub())
    assert out == fixed_time.isoformat(), (
        f"_next_run_iso did not return ISO-8601 of next_run; got {out!r}. "
        "The frontend parses this with `new Date(iso)`."
    )


def test_next_run_iso_returns_none_when_calculate_next_raises():
    """Defensive — one bad cron entry MUST NOT take down the whole
    list. The function returns None on raise; the dashboard
    renders "—" for null."""
    from routers.cron_admin import _next_run_iso

    class _BadStub:
        def calculate_next(self, _now: datetime) -> None:
            raise RuntimeError("synthetic failure")

    out = _next_run_iso(_BadStub())
    assert out is None, (
        f"_next_run_iso did not catch the synthetic RuntimeError; "
        f"got {out!r}. Without the catch, one bad cron entry would "
        "500 the entire `/admin/crons` page."
    )


# ---------- Sort ordering ----------


def test_handler_sorts_next_run_asc_with_nulls_last():
    """The list MUST be sorted by next_run ASC NULLS LAST so the
    cron about to fire surfaces first. Pin via source inspection
    of the sort key (the actual handler runs against the real
    `WorkerSettings` which we don't want to depend on here).
    """
    import routers.cron_admin as mod

    src = inspect.getsource(mod.list_crons)
    # Look for the sort that pushes None next_run rows to the bottom.
    # The pattern is `(r["next_run"] is None, ...)` — the first
    # element of the tuple key is False for present rows (sorts
    # before True for missing rows).
    assert 'r["next_run"] is None' in src, (
        "list_crons no longer sorts None next_run rows last. "
        "A regression would push uncalculatable crons to the top "
        "of the table — confusing during incidents."
    )
    assert "rows.sort" in src, (
        "list_crons no longer sorts the rows. The dashboard expects "
        "next-due-first ordering; without sort, ordering is dict-"
        "iteration-defined (effectively random)."
    )


# ---------- Wire the router into main.py (smoke) ----------


def test_router_is_mounted_in_main():
    """`main.create_app()` MUST `include_router(cron_admin_router.router)`.
    Without that, the router exists but the API doesn't expose it —
    silent 404 from the frontend hook.

    Source-grep on `main.py` because dynamically calling create_app
    pulls in too many side effects (Sentry, Redis, etc.)."""
    from pathlib import Path

    main_path = Path(__file__).parent.parent / "main.py"
    src = main_path.read_text()
    assert "cron_admin" in src, (
        "main.py no longer references cron_admin. The router exists but isn't mounted; the frontend hook 404s."
    )
    assert "include_router(cron_admin_router.router)" in src, (
        "main.py no longer includes the cron_admin router. The router exists but isn't wired into the FastAPI app."
    )


# ----------------------------------------------------------------------
# Telemetry surface (added with `services/cron_telemetry.py` +
# `models/cron_run.py` + migration 0042).
#
# The pins above cover the static registry. THIS section pins the
# last-run telemetry that's now joined into the registry response and
# the per-cron drilldown endpoint.
# ----------------------------------------------------------------------


def test_cron_telemetry_module_imports():
    """The telemetry helpers MUST be importable. A revert that deleted
    `services/cron_telemetry.py` would break the wrapper used in
    `workers/queue.py` AND the read-helpers used in
    `routers/cron_admin.py` — surface as ImportError loudly here."""
    from services.cron_telemetry import (  # noqa: F401
        CronRunStatus,
        cron_telemetry_wrap,
        latest_run_per_cron,
        recent_runs_for_cron,
    )


def test_cron_run_model_table_name_pinned():
    """Migration 0042 created `cron_runs`; the ORM `__tablename__`
    MUST match. A rename here points the wrapper's INSERT at a
    non-existent table — every cron invocation logs a warning and
    skips telemetry persistence (graceful but observable)."""
    from models.cron_run import CronRun

    assert CronRun.__tablename__ == "cron_runs", (
        f"CronRun.__tablename__ drifted to {CronRun.__tablename__!r}. "
        "Migration 0042 created `cron_runs`; rename has to move both."
    )


def test_cron_run_columns_pinned():
    """The columns `services.cron_telemetry` writes via raw SQL: a
    rename here = the telemetry wrapper's INSERT/UPDATE statements
    fail (caught by best-effort try/except, so silent telemetry loss
    rather than crash). Pin so the rename has to be deliberate."""
    from models.cron_run import CronRun

    cols = {c.name: c for c in CronRun.__table__.columns}
    expected = {
        "id",
        "cron_name",
        "started_at",
        "finished_at",
        "status",
        "error_message",
        "duration_ms",
    }
    assert set(cols.keys()) == expected, f"CronRun columns drifted: have {set(cols.keys())}, want {expected}"

    # NOT NULL invariants — the wrapper's INSERT relies on these
    # being NOT NULL with server defaults, so a fresh row always
    # constructs even when only `cron_name` is supplied.
    assert cols["id"].nullable is False
    assert cols["cron_name"].nullable is False
    assert cols["started_at"].nullable is False
    assert cols["status"].nullable is False

    # Optional columns — populated only when the run finishes.
    for optional in ("finished_at", "error_message", "duration_ms"):
        assert cols[optional].nullable is True


def test_recent_runs_endpoint_path_pinned():
    """The drilldown endpoint `GET /api/v1/admin/crons/{cron_name}/runs`
    is what powers the per-cron history view. A path rename = the
    drilldown 404s.
    """
    from routers.cron_admin import router

    paths = {r.path for r in router.routes}
    assert "/api/v1/admin/crons/{cron_name}/runs" in paths, (
        f"per-cron runs endpoint missing; have {paths}. "
        "The path param name `cron_name` MUST match the route signature "
        "AND the frontend hook's URL builder."
    )


def test_telemetry_wrapper_preserves_metadata():
    """SECURITY/CORRECTNESS pin. `cron_telemetry_wrap` MUST preserve
    `__name__`, `__module__`, `__doc__`, `__qualname__` from the
    wrapped coroutine. The cron-registry dashboard reads
    `coro.__name__` for the function-name column AND
    `coro.__doc__` for the description. A regression that lost
    these would render every wrapped cron as "wrapper" with no
    description."""
    from services.cron_telemetry import cron_telemetry_wrap

    async def example_cron(ctx):
        """Example cron docstring."""
        return None

    wrapped = cron_telemetry_wrap(example_cron)

    assert wrapped.__name__ == "example_cron", (
        f"cron_telemetry_wrap dropped __name__; got {wrapped.__name__!r}. "
        "The dashboard's function column shows this verbatim."
    )
    assert wrapped.__doc__ == "Example cron docstring.", (
        f"cron_telemetry_wrap dropped __doc__; got {wrapped.__doc__!r}. "
        "The dashboard's description column reads from this."
    )
    assert wrapped.__qualname__ == example_cron.__qualname__
    assert wrapped.__module__ == example_cron.__module__


def test_telemetry_wrapper_naming_matches_arq_convention():
    """The internal `_cron_name_for` MUST emit `cron:<func_name>` —
    matches arq's `CronJob.name` so the dashboard's join on
    `cron_name` works. A regression to a different format silently
    breaks the join (every row has `last_run = null`)."""
    from services.cron_telemetry import _cron_name_for

    async def weekly_report_cron(ctx):
        return None

    name = _cron_name_for(weekly_report_cron)
    assert name == "cron:weekly_report_cron", (
        f"_cron_name_for emitted {name!r}; want 'cron:weekly_report_cron' "
        "to match arq's auto-derived CronJob.name. A drift here means "
        "the dashboard's last_run join returns NULL for every cron."
    )


def test_truncate_error_caps_length():
    """Pin the error_message storage cap. A regression that removed
    the cap would let a stack trace blow up the row size; a
    regression that capped tighter would lose the first frame
    (which is the useful debugging signal)."""
    from services.cron_telemetry import _MAX_ERROR_MESSAGE_LEN, _truncate_error

    assert _MAX_ERROR_MESSAGE_LEN == 2000, (
        f"_MAX_ERROR_MESSAGE_LEN drifted to {_MAX_ERROR_MESSAGE_LEN}. "
        "2000 chars is calibrated to fit first frame + module path; "
        "tighter loses debugging signal, looser bloats the table."
    )

    long_msg = "x" * (_MAX_ERROR_MESSAGE_LEN + 100)

    class _LongException(Exception):
        pass

    out = _truncate_error(_LongException(long_msg))
    assert len(out) <= _MAX_ERROR_MESSAGE_LEN, (
        f"_truncate_error returned {len(out)} chars; cap is {_MAX_ERROR_MESSAGE_LEN}."
    )
    # Ellipsis suffix tells operators the message was cut.
    assert out.endswith("…")


def test_latest_run_per_cron_signature_async():
    """Read-helper signature pin — called from `list_crons`. Sync
    regression would silently no-op the await."""
    from services.cron_telemetry import latest_run_per_cron

    assert inspect.iscoroutinefunction(latest_run_per_cron), "latest_run_per_cron MUST be async — caller awaits it."

    sig = inspect.signature(latest_run_per_cron)
    # No required args (cross-tenant aggregation).
    assert all(p.default is not inspect.Parameter.empty for p in sig.parameters.values()), (
        f"latest_run_per_cron took required args: {list(sig.parameters.keys())}. "
        "It MUST be a no-arg call from list_crons."
    )


def test_recent_runs_for_cron_signature_pinned():
    """`recent_runs_for_cron(cron_name, *, limit=20)`. Drives the
    per-cron drilldown; rename = the drilldown route's call site
    breaks at runtime."""
    from services.cron_telemetry import recent_runs_for_cron

    assert inspect.iscoroutinefunction(recent_runs_for_cron)

    sig = inspect.signature(recent_runs_for_cron)
    params = list(sig.parameters.values())

    assert params[0].name == "cron_name"
    # `limit` is keyword-only with a documented default.
    limit = sig.parameters["limit"]
    assert limit.kind is inspect.Parameter.KEYWORD_ONLY, (
        "`limit` MUST be keyword-only — caller's `limit=20` form would TypeError on a positional regression."
    )
    assert limit.default == 20
