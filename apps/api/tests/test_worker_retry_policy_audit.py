"""Worker job retry-policy audit.

The bug class
-------------
Two task systems, two failure modes:

1. **arq (`apps/api/workers/queue.py`).** Default `max_tries=5`,
   default `retry_jitter=0`. The missing jitter matters: when 100
   webhook deliveries fail simultaneously and all retry at exactly
   `now + 5s`, they hammer the downstream as a thundering herd.
   `retry_jitter` adds a random component — without it, the herd
   stays in lock-step.

2. **Celery (`apps/worker/tasks.py`).** Default `max_retries=3`,
   default `default_retry_delay=180s`. Tasks that don't declare
   `max_retries` retry forever silently on transient failures
   (network blips, redis flaps).

What this audit checks
----------------------
- arq: `WorkerSettings` declares `max_tries` AND `retry_jitter`,
  OR each function in `WorkerSettings.functions` has explicit
  retry config via `@func()` decorator parameters.

- Celery: every `@app.task(...)` invocation passes `max_retries`
  (we accept any value — the audit's purpose is "the field is
  populated at all," not "the value is correct").

Same ratchet pattern as the prior audits.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_API_ROOT = Path(__file__).resolve().parent.parent
_REPO_ROOT = _API_ROOT.parent.parent
_QUEUE_PY = _API_ROOT / "workers" / "queue.py"
_CELERY_TASKS = _REPO_ROOT / "apps" / "worker" / "tasks.py"


# Today's baselines. Set to today's count so the ratchet starts at
# reality. Goal is for both to drop to 0 — `max_tries`/`retry_jitter`
# pinned on `WorkerSettings`, and `max_retries=` on every Celery task.
BASELINE_ARQ_RETRY_GAPS = 2  # both max_tries and retry_jitter unset on WorkerSettings
BASELINE_CELERY_TASKS_NO_MAX_RETRIES = 3


def _parse_queue_py() -> ast.Module | None:
    if not _QUEUE_PY.exists():
        return None
    return ast.parse(_QUEUE_PY.read_text(encoding="utf-8"))


def _worker_settings_class(tree: ast.Module) -> ast.ClassDef | None:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "WorkerSettings":
            return node
    return None


def _worker_settings_attr_names(cls: ast.ClassDef) -> set[str]:
    """Top-level assignments in WorkerSettings — these are the
    arq config fields."""
    out: set[str] = set()
    for stmt in cls.body:
        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Name):
                    out.add(target.id)
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            out.add(stmt.target.id)
    return out


def test_arq_worker_settings_declares_retry_policy():
    """`WorkerSettings` should declare `max_tries` AND `retry_jitter`
    (or the equivalent per-function decoration). Default arq behaviour
    leaves both implicit, which is the thundering-herd shape under
    burst failures.

    Same ratchet pattern. Failure surfaces both directions.
    """
    tree = _parse_queue_py()
    assert tree is not None, "apps/api/workers/queue.py is missing"

    cls = _worker_settings_class(tree)
    assert cls is not None, "WorkerSettings class not found in queue.py"

    attrs = _worker_settings_attr_names(cls)
    missing: list[str] = []
    if "max_tries" not in attrs:
        missing.append("max_tries")
    if "retry_jitter" not in attrs:
        missing.append("retry_jitter")

    n = len(missing)
    if n > BASELINE_ARQ_RETRY_GAPS:
        new = n - BASELINE_ARQ_RETRY_GAPS
        pytest.fail(
            f"{new} new missing arq retry-policy field(s) "
            f"(total now {n}, baseline {BASELINE_ARQ_RETRY_GAPS}):\n  "
            + "\n  ".join(missing)
            + "\n\nAdd to `WorkerSettings`:\n"
            "    max_tries = 5      # explicit; arq default is 5 too,\n"
            "                       # but pin so a future arq bump can't\n"
            "                       # silently change retry semantics.\n"
            "    retry_jitter = 30  # ±30s spread — without this, 100\n"
            "                       # simultaneous failures all retry\n"
            "                       # at exactly now+5s, hammering the\n"
            "                       # downstream as a thundering herd.\n\n"
            "If a specific job needs different retry semantics, use the\n"
            "per-function `@func(max_tries=…)` decorator and add the\n"
            "function name to a per-job allowlist."
        )
    if n < BASELINE_ARQ_RETRY_GAPS:
        pytest.fail(
            f"arq retry-gap count dropped from {BASELINE_ARQ_RETRY_GAPS} "
            f"to {n}. 🎉 Update `BASELINE_ARQ_RETRY_GAPS` to {n}."
        )


def _is_celery_task_decorator(dec: ast.expr) -> bool:
    """Recognises `@app.task(...)`, `@celery_app.task(...)`, etc."""
    if not isinstance(dec, ast.Call):
        return False
    func = dec.func
    if not isinstance(func, ast.Attribute):
        return False
    return func.attr == "task"


def _has_max_retries_kwarg(dec: ast.Call) -> bool:
    return any(kw.arg == "max_retries" and kw.value is not None for kw in dec.keywords)


def test_every_celery_task_declares_max_retries():
    """Every `@app.task(...)` in `apps/worker/tasks.py` should
    pass `max_retries`. Without it, transient failures retry up to
    Celery's default (3) but with no per-task tuning — and the
    operator can't tell at the call site whether the default is
    appropriate for THIS task."""
    if not _CELERY_TASKS.exists():
        pytest.skip("apps/worker/tasks.py not present in this repo state")
    tree = ast.parse(_CELERY_TASKS.read_text(encoding="utf-8"))

    missing: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not _is_celery_task_decorator(dec):
                continue
            assert isinstance(dec, ast.Call)
            if not _has_max_retries_kwarg(dec):
                missing.append(f"{node.name}  (line {dec.lineno})")

    n = len(missing)
    if n > BASELINE_CELERY_TASKS_NO_MAX_RETRIES:
        new = n - BASELINE_CELERY_TASKS_NO_MAX_RETRIES
        pytest.fail(
            f"{new} new Celery task(s) without `max_retries=` "
            f"(total now {n}, baseline {BASELINE_CELERY_TASKS_NO_MAX_RETRIES}):\n  "
            + "\n  ".join(missing)
            + "\n\nAdd `max_retries=N` to each `@app.task(...)`. Pick a "
            "value the operator can defend — `max_retries=3` for a "
            "transient-network task, `max_retries=0` for a never-retry "
            "side-effect."
        )
    if n < BASELINE_CELERY_TASKS_NO_MAX_RETRIES:
        pytest.fail(
            f"Celery-no-max_retries count dropped from "
            f"{BASELINE_CELERY_TASKS_NO_MAX_RETRIES} to {n}. 🎉 "
            f"Update the baseline."
        )


def test_audit_recognises_documented_decorator_shapes():
    """Defensive: positive + negative AST fixtures. A regression
    in `_is_celery_task_decorator` would silently let undeclared
    retry policies through.
    """
    pos = ast.parse("from celery import Celery\napp = Celery()\n@app.task(name='x', max_retries=3)\ndef f(): pass\n")
    fn = pos.body[-1]
    assert isinstance(fn, ast.FunctionDef)
    dec = fn.decorator_list[0]
    assert _is_celery_task_decorator(dec)
    assert isinstance(dec, ast.Call)
    assert _has_max_retries_kwarg(dec)

    pos_no_retries = ast.parse("@app.task(name='x')\ndef f(): pass\n")
    fn = pos_no_retries.body[0]
    assert isinstance(fn, ast.FunctionDef)
    dec = fn.decorator_list[0]
    assert _is_celery_task_decorator(dec)
    assert isinstance(dec, ast.Call)
    assert not _has_max_retries_kwarg(dec)

    # Non-task decorator → not detected.
    neg = ast.parse("@dataclass\nclass C: pass\n")
    cls = neg.body[0]
    assert isinstance(cls, ast.ClassDef)
    assert not _is_celery_task_decorator(cls.decorator_list[0])
