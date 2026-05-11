"""Logger eager-formatting audit.

The bug class
-------------
Pre-formatted log messages defeat the logging library's level
filter:

    logger.debug(f"expensive_query={expensive_call()}")

`expensive_call()` runs even when the active log level is
WARNING (i.e. DEBUG is suppressed) — the f-string is built
*before* `logger.debug` decides whether to emit the line.

The fix is to hand the formatting work to the logger:

    logger.debug("expensive_query=%s", expensive_call())

Now `logger.debug` checks `isEnabledFor(DEBUG)` first, returns
early on a no-op, and `expensive_call()` is never invoked.

Three eager-formatting shapes catch every variant we've seen
in this codebase:

  1. f-string:           `logger.info(f"x={x}")`
  2. `.format()` method: `logger.info("x={}".format(x))`
  3. string concat / `%`: `logger.info("x=" + str(x))`,
                          `logger.info("x=%s" % x)`

All three eagerly build the final string. `%s`-with-positional-
args is the canonical lazy shape; the logging library applies the
substitution itself (lazily) only if the level is enabled.

What this audit checks
----------------------
AST walk over `apps/api/{core,db,middleware,models,routers,
schemas,services,workers}/*.py` plus `apps/worker/*.py`. For
every recognised logger call (see "Recognised logger names"
below), inspect the message argument:

  * For `.debug/.info/.warning/.error/.exception/.critical`:
    message is `args[0]`.
  * For `.log(level, msg, ...)`: message is `args[1]`.

Flag the call if the message arg is:

  * `ast.JoinedStr` — an f-string (regardless of whether
    interpolations are present; consistency over edge cases).
  * `ast.Call` whose `func` is `<str>.format`.
  * `ast.BinOp` with `Add` (string concat) where one operand
    is a string-shaped node, OR `Mod` (`%`) where the left
    operand is a string-shaped node.

What's NOT checked
------------------
- `tests/` — eager formatting in tests is fine; tests don't run
  in production and DEBUG is usually on anyway.
- `scripts/` — operator-facing CLI tools have their own logger
  config; eager formatting is acceptable there.
- Alembic migrations — same reason as scripts.
- Logger calls reached through arbitrary Attribute chains
  (e.g. `module.submodule.logger.info(...)`). The codebase
  convention is module-level `logger = logging.getLogger(__name__)`;
  a non-conforming chain would surface during code review.

Recognised logger names
-----------------------
First-component name must be one of: `logger`, `log`,
`_logger`, `_log`. The `self.<x>` attribute pattern is also
matched (for class-method loggers). Other names — pylint's
`logging-not-lazy` regex would catch them — slip past this
audit; if a new project convention emerges, add the name to
`_LOG_NAMES` below.

Recognised logger methods
-------------------------
`debug`, `info`, `warning`, `error`, `exception`, `critical`,
`log` (the level-explicit variant). The catch-all on `log`
correctly handles the `args[1]` shift.

Allowlist
---------
Per-(file, line) for legitimate cases. Each entry needs a
stated reason — an empty rationale silences the gate. The
canonical legitimate case is a startup banner where the cost
of a single eager format is negligible AND the line is always
emitted at INFO+:

    # ALLOWLIST: server boot — banner, always emitted
    logger.info(f"AEC API ready on :{settings.PORT}")

Same ratchet pattern as `test_print_in_production_audit.py`.
Today's baseline is 0 (the codebase already uses
`%s`-with-positional-args throughout); the audit pins that
property so a future regression is caught at PR time.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_API_ROOT = _REPO_ROOT / "apps" / "api"
_SCAN_ROOTS: list[Path] = [
    _API_ROOT / "core",
    _API_ROOT / "db",
    _API_ROOT / "middleware",
    _API_ROOT / "models",
    _API_ROOT / "routers",
    _API_ROOT / "schemas",
    _API_ROOT / "services",
    _API_ROOT / "workers",
    _REPO_ROOT / "apps" / "worker",
]


# Today's baseline. The codebase uses %s-with-positional-args
# throughout; this pin protects that property going forward.
BASELINE_EAGER_LOGGER_CALLS = 0  # 2026-05: zero offenders on first run; ratchet pinned.


# Per-(relative_posix_path, line) allowlist. Each entry needs a
# stated reason — an empty rationale silences the gate.
ALLOWLIST: dict[tuple[str, int], str] = {
    # No entries today.
}


_LOG_NAMES: frozenset[str] = frozenset({"logger", "log", "_logger", "_log"})
_LOG_METHODS: frozenset[str] = frozenset({"debug", "info", "warning", "error", "exception", "critical", "log"})


def _scan_files() -> list[Path]:
    out: list[Path] = []
    for root in _SCAN_ROOTS:
        if not root.exists():
            continue
        for p in root.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            # Test files — eager formatting is fine in tests.
            if "tests" in p.parts:
                continue
            # Scripts — operator-facing CLI has its own logger
            # convention; eager formatting OK there.
            if "scripts" in p.parts:
                continue
            # Alembic migrations — same as scripts.
            if "alembic" in p.parts:
                continue
            out.append(p)
    return sorted(out)


def _is_string_shaped(node: ast.AST) -> bool:
    """True if `node` produces a string at runtime in the shapes
    we need to recognise: literal str, f-string, or a chain of
    str-add concats."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return True
    if isinstance(node, ast.JoinedStr):
        return True
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _is_string_shaped(node.left) or _is_string_shaped(node.right)
    return False


def _is_logger_call(node: ast.AST) -> bool:
    """Match `<logger>.<method>(...)`.

    `<logger>` is one of the names in `_LOG_NAMES`, OR a
    `self.<one of those names>` attribute access.
    `<method>` is one of `_LOG_METHODS`.
    """
    if not isinstance(node, ast.Call):
        return False
    if not isinstance(node.func, ast.Attribute):
        return False
    if node.func.attr not in _LOG_METHODS:
        return False
    val = node.func.value
    # `logger.info(...)`, `_log.debug(...)`, etc.
    if isinstance(val, ast.Name) and val.id in _LOG_NAMES:
        return True
    # `self.logger.info(...)`, `self._log.warning(...)`, etc.
    if (
        isinstance(val, ast.Attribute)
        and val.attr in _LOG_NAMES
        and isinstance(val.value, ast.Name)
        and val.value.id == "self"
    ):
        return True
    return False


def _message_arg(call: ast.Call) -> ast.AST | None:
    """Return the argument that holds the log message string.

    For `.log(level, msg, ...)`, msg is `args[1]`. For every
    other recognised method, msg is `args[0]`.
    """
    if not call.args:
        return None
    if isinstance(call.func, ast.Attribute) and call.func.attr == "log":
        return call.args[1] if len(call.args) >= 2 else None
    return call.args[0]


def _eager_kind(arg: ast.AST | None) -> str | None:
    """Classify eager-formatting shape for diagnostic output.
    Returns None if the argument is not eagerly-formatted.
    """
    if arg is None:
        return None
    if isinstance(arg, ast.JoinedStr):
        return "f-string"
    if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute) and arg.func.attr == "format":
        return ".format()"
    if isinstance(arg, ast.BinOp):
        if isinstance(arg.op, ast.Add) and (_is_string_shaped(arg.left) or _is_string_shaped(arg.right)):
            return "string concat"
        if isinstance(arg.op, ast.Mod) and _is_string_shaped(arg.left):
            return "% formatting"
    return None


def _scan_file(path: Path) -> list[tuple[str, int, str, str]]:
    """Return findings: (rel_path, line, kind, source_line)."""
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    rel = path.relative_to(_REPO_ROOT).as_posix()
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return []
    out: list[tuple[str, int, str, str]] = []
    lines = text.splitlines()
    for node in ast.walk(tree):
        if not _is_logger_call(node):
            continue
        assert isinstance(node, ast.Call)  # narrow for type-checkers
        kind = _eager_kind(_message_arg(node))
        if kind is None:
            continue
        line = node.lineno
        if (rel, line) in ALLOWLIST:
            continue
        try:
            source_line = lines[line - 1].strip()[:80]
        except IndexError:
            source_line = "<unknown>"
        out.append((rel, line, kind, source_line))
    return out


def _audit_all() -> list[tuple[str, int, str, str]]:
    out: list[tuple[str, int, str, str]] = []
    for path in _scan_files():
        out.extend(_scan_file(path))
    return out


def test_no_eager_formatted_logger_calls():
    """Every logger call should hand formatting to the logging
    library: `logger.info("x=%s", x)`, not `logger.info(f"x={x}")`.

    Eager formatting (f-string, `.format()`, concat, `%`) builds
    the final string before the logger checks `isEnabledFor`,
    which means `logger.debug(...)` runs the formatting cost even
    when DEBUG is suppressed at the active log level.
    """
    findings = _audit_all()
    n = len(findings)
    if n > BASELINE_EAGER_LOGGER_CALLS:
        new = n - BASELINE_EAGER_LOGGER_CALLS
        rendered = [f"{rel}:{line}  [{kind}]  {src}" for rel, line, kind, src in findings[:20]]
        pytest.fail(
            f"{new} new eager-formatted logger call(s) "
            f"(total now {n}, baseline {BASELINE_EAGER_LOGGER_CALLS}):\n  "
            + "\n  ".join(rendered)
            + (f"\n  … and {n - 20} more" if n > 20 else "")
            + "\n\nReplace eager formatting with %s-and-positional-args:\n"
            "    # was (eager — formats even when DEBUG suppressed):\n"
            "    logger.debug(f'received {payload}')\n"
            "    logger.error('failed: ' + str(exc))\n"
            "    logger.warning('count={}'.format(n))\n"
            "    # use (lazy — logger checks level first):\n"
            "    logger.debug('received %s', payload)\n"
            "    logger.error('failed: %s', exc)\n"
            "    logger.warning('count=%s', n)\n\n"
            "Why it matters: f-string / .format() / concat builds the "
            "final string before the logger decides whether to emit. "
            "At LOGLEVEL=WARNING, every logger.debug(f'...') still pays "
            "the formatting cost. The %s shape defers formatting to "
            "the logger's own pipeline, which short-circuits on a "
            "level check.\n\n"
            "If a specific call is genuinely worth the eager format "
            "(e.g. a startup banner that's always emitted), add a "
            "stated-reason entry to ALLOWLIST."
        )
    if n < BASELINE_EAGER_LOGGER_CALLS:
        pytest.fail(
            f"Eager-logger count dropped from {BASELINE_EAGER_LOGGER_CALLS} "
            f"to {n}. 🎉 Update `BASELINE_EAGER_LOGGER_CALLS` to {n}."
        )


def test_audit_recognises_documented_shapes():
    """Defensive: positive + negative AST fixtures so a refactor
    of the detection logic surfaces here as a clean failure.
    """
    # Positive: f-string with interpolation.
    pos_fstr = ast.parse('logger.info(f"x={x}")\n')
    calls = [n for n in ast.walk(pos_fstr) if _is_logger_call(n)]
    assert len(calls) == 1
    assert _eager_kind(_message_arg(calls[0])) == "f-string"

    # Positive: f-string with NO interpolation — still flagged
    # for consistency. A future variable interpolation would
    # otherwise sneak in below the radar.
    pos_fstr_static = ast.parse('logger.info(f"plain string")\n')
    calls = [n for n in ast.walk(pos_fstr_static) if _is_logger_call(n)]
    assert _eager_kind(_message_arg(calls[0])) == "f-string"

    # Positive: .format() call.
    pos_format = ast.parse('logger.warning("x={}".format(x))\n')
    calls = [n for n in ast.walk(pos_format) if _is_logger_call(n)]
    assert _eager_kind(_message_arg(calls[0])) == ".format()"

    # Positive: string concat with `+`.
    pos_concat = ast.parse('logger.error("failed: " + str(exc))\n')
    calls = [n for n in ast.walk(pos_concat) if _is_logger_call(n)]
    assert _eager_kind(_message_arg(calls[0])) == "string concat"

    # Positive: % formatting (legacy %-style applied eagerly).
    pos_mod = ast.parse('logger.info("x=%s" % x)\n')
    calls = [n for n in ast.walk(pos_mod) if _is_logger_call(n)]
    assert _eager_kind(_message_arg(calls[0])) == "% formatting"

    # Positive: .log(level, msg) — message is at args[1].
    pos_log = ast.parse('logger.log(logging.INFO, f"x={x}")\n')
    calls = [n for n in ast.walk(pos_log) if _is_logger_call(n)]
    assert _eager_kind(_message_arg(calls[0])) == "f-string"

    # Positive: self.<logger>.method(...).
    pos_self = ast.parse('self.logger.error(f"x={x}")\n')
    calls = [n for n in ast.walk(pos_self) if _is_logger_call(n)]
    assert len(calls) == 1
    assert _eager_kind(_message_arg(calls[0])) == "f-string"

    # Negative: %s + positional args (the canonical lazy shape).
    neg_lazy = ast.parse('logger.info("x=%s", x)\n')
    calls = [n for n in ast.walk(neg_lazy) if _is_logger_call(n)]
    assert len(calls) == 1
    assert _eager_kind(_message_arg(calls[0])) is None

    # Negative: plain string literal, no formatting.
    neg_literal = ast.parse('logger.info("static message")\n')
    calls = [n for n in ast.walk(neg_literal) if _is_logger_call(n)]
    assert _eager_kind(_message_arg(calls[0])) is None

    # Negative: bare logger reference, not a call.
    neg_ref = ast.parse("fn = logger.info\n")
    calls = [n for n in ast.walk(neg_ref) if _is_logger_call(n)]
    assert calls == []

    # Negative: print(f"...") — `print` is not a logger.
    neg_print = ast.parse('print(f"x={x}")\n')
    calls = [n for n in ast.walk(neg_print) if _is_logger_call(n)]
    assert calls == []

    # Negative: .log() with no message arg — not flagged (no
    # message means nothing to flag; a missing-arg error would
    # surface elsewhere).
    neg_log_noarg = ast.parse("logger.log(logging.INFO)\n")
    calls = [n for n in ast.walk(neg_log_noarg) if _is_logger_call(n)]
    assert _eager_kind(_message_arg(calls[0])) is None

    # Negative: numeric `+` (not a string concat).
    neg_numeric = ast.parse("logger.info(a + b)\n")
    calls = [n for n in ast.walk(neg_numeric) if _is_logger_call(n)]
    assert _eager_kind(_message_arg(calls[0])) is None


def test_allowlist_entries_actually_correspond_to_real_eager_calls():
    """Defensive: stale ALLOWLIST entries silently mask future
    regressions on the line of the renamed call. Same shape as
    the print-audit's stale-entry test.
    """
    if not ALLOWLIST:
        return
    real: set[tuple[str, int]] = set()
    for path in _scan_files():
        for rel, line, _kind, _src in _scan_file(path):
            real.add((rel, line))
    stale = [k for k in ALLOWLIST if k not in real]
    assert not stale, f"Stale ALLOWLIST entries: {stale}."
