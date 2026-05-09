"""`logger.exception(...)` outside an `except` block audit.

The bug class
-------------
`logging.Logger.exception(msg)` is shorthand for
`logger.error(msg, exc_info=True)`. The `exc_info=True` part
calls `sys.exc_info()` to format the active exception's
traceback into the log line.

The catch: `sys.exc_info()` only returns a meaningful value
INSIDE an `except` block. Anywhere else it returns
`(None, None, None)`. So `logger.exception(...)` outside an
`except` block produces:

    ERROR    your.module:42 something went wrong
    NoneType: None

A useless tombstone — the operator sees the message but no
traceback, no exception type, no stack. The bug whose context
they came to look up is invisible.

The fix is contextual:
  * Inside `except`: `logger.exception(...)` is correct.
  * Outside: use `logger.error(...)` (no traceback formatting).

What this audit checks
----------------------
AST walk over `apps/api/{core,db,middleware,models,routers,
schemas,services,workers}/*.py` plus `apps/worker/*.py`. For
every `<name>.exception(...)` call where the receiver matches
a logger-like name (`logger`, `log`, `LOG`, `_logger`), assert
the call is lexically inside an `ast.ExceptHandler`.

What's NOT checked
------------------
- `Exception` subclasses with `.exception` methods (rare in
  this codebase) — receiver-name filter excludes them.
- `traceback.format_exc()` outside except — same bug, different
  shape; not in scope here.
- Test files — out of scope.

Same ratchet pattern as the other audits.
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


# Today's baseline. Filled in on first run.
BASELINE_LOGGER_EXCEPTION_OUTSIDE_EXCEPT = 0


# Receiver names that look logger-like.
_LOGGER_NAMES: frozenset[str] = frozenset({"logger", "log", "LOG", "_logger"})


# Per-(file, line) allowlist. Each entry needs a stated reason.
ALLOWLIST: dict[tuple[str, int], str] = {
    # No entries today.
}


def _scan_files() -> list[Path]:
    out: list[Path] = []
    for root in _SCAN_ROOTS:
        if not root.exists():
            continue
        for p in root.rglob("*.py"):
            if "__pycache__" in p.parts or "tests" in p.parts:
                continue
            out.append(p)
    return sorted(out)


def _is_logger_exception_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr != "exception":
        return False
    recv = func.value
    return isinstance(recv, ast.Name) and recv.id in _LOGGER_NAMES


def _collect_offenders(tree: ast.AST) -> list[int]:
    """Return line numbers of every `logger.exception(...)` NOT
    inside an `ast.ExceptHandler`."""
    out: list[int] = []

    def visit(node: ast.AST, in_except: bool) -> None:
        if _is_logger_exception_call(node):
            if not in_except:
                out.append(node.lineno)
            return
        # Crossing into an ExceptHandler flips the flag for the
        # subtree.
        next_in_except = in_except or isinstance(node, ast.ExceptHandler)
        for child in ast.iter_child_nodes(node):
            visit(child, next_in_except)

    visit(tree, in_except=False)
    return out


def _scan_file(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    rel = path.relative_to(_REPO_ROOT).as_posix()
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return []
    findings: list[str] = []
    for line in _collect_offenders(tree):
        if (rel, line) in ALLOWLIST:
            continue
        try:
            source_line = text.splitlines()[line - 1].strip()[:80]
        except IndexError:
            source_line = "<unknown>"
        findings.append(f"{rel}:{line}  {source_line}")
    return findings


def _audit_all() -> list[str]:
    out: list[str] = []
    for path in _scan_files():
        out.extend(_scan_file(path))
    return out


def test_no_logger_exception_outside_except():
    """Every `logger.exception(...)` should sit inside an
    `except` block. Outside one, `sys.exc_info()` returns
    `(None, None, None)` and the call logs a useless tombstone.
    """
    findings = _audit_all()
    n = len(findings)
    if n > BASELINE_LOGGER_EXCEPTION_OUTSIDE_EXCEPT:
        new = n - BASELINE_LOGGER_EXCEPTION_OUTSIDE_EXCEPT
        pytest.fail(
            f"{new} new `logger.exception(...)` call(s) outside except "
            f"(total now {n}, baseline {BASELINE_LOGGER_EXCEPTION_OUTSIDE_EXCEPT}):\n  "
            + "\n  ".join(findings[:20])
            + (f"\n  … and {n - 20} more" if n > 20 else "")
            + "\n\nFix:\n"
            "    # outside except — use logger.error\n"
            "    logger.error('something went wrong')\n\n"
            "    # inside except — logger.exception is correct\n"
            "    try:\n"
            "        risky()\n"
            "    except Exception:\n"
            "        logger.exception('risky failed')\n\n"
            "Outside an except, `sys.exc_info()` returns "
            "(None, None, None) and the formatted log line is "
            "`<msg>\\nNoneType: None` — no traceback, no exception "
            "type. The operator sees the message but loses every "
            "diagnostic the .exception() method was supposed to add."
        )
    if n < BASELINE_LOGGER_EXCEPTION_OUTSIDE_EXCEPT:
        pytest.fail(
            f"logger.exception-outside-except count dropped from "
            f"{BASELINE_LOGGER_EXCEPTION_OUTSIDE_EXCEPT} to {n}. 🎉 "
            f"Update `BASELINE_LOGGER_EXCEPTION_OUTSIDE_EXCEPT` to {n}."
        )


def test_audit_recognises_documented_shapes():
    """Defensive: positive + negative AST fixtures."""
    # Positive: outside except.
    pos = ast.parse(
        "import logging\n"
        "logger = logging.getLogger(__name__)\n"
        "def f():\n"
        "    logger.exception('bad')\n"
    )
    out = _collect_offenders(pos)
    assert out == [4], f"Expected line 4, got {out}"

    # Negative: inside except.
    neg = ast.parse(
        "import logging\n"
        "logger = logging.getLogger(__name__)\n"
        "def g():\n"
        "    try:\n"
        "        risky()\n"
        "    except Exception:\n"
        "        logger.exception('caught')\n"
    )
    out = _collect_offenders(neg)
    assert out == [], f"Audit false-flagged inside-except: {out}"

    # Negative: nested in except's else / finally would also count
    # as outside the except — but the AST puts those on the parent
    # Try, not the ExceptHandler. We accept this edge case as
    # genuinely outside except (sys.exc_info() really IS cleared
    # in else/finally).
    neg2 = ast.parse(
        "import logging\n"
        "logger = logging.getLogger(__name__)\n"
        "def h():\n"
        "    try:\n"
        "        risky()\n"
        "    except Exception:\n"
        "        pass\n"
        "    finally:\n"
        "        logger.exception('cleanup')\n"
    )
    out = _collect_offenders(neg2)
    assert out == [9], f"Audit should flag finally-block: {out}"

    # Negative: unrelated `.exception` method on a non-logger.
    neg3 = ast.parse(
        "def k(req):\n"
        "    return req.exception()\n"
    )
    out = _collect_offenders(neg3)
    assert out == [], f"Audit should ignore non-logger receiver: {out}"
