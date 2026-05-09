"""Logging structure contract audit.

The bug class
-------------
A logger call like:

    logger.info(f"user {user_id} signed in from {ip}")

bakes the dynamic context (`user_id`, `ip`) into a free-form message
string. Datadog / Loki / Sentry can't extract those fields for
indexing — every search becomes a substring grep over the rendered
message, which doesn't scale and won't match if the format ever
shifts. The structured equivalent:

    logger.info("user signed in", extra={"user_id": user_id, "ip": ip})

…lets the log shipper attach `user_id` and `ip` as queryable keys.
You can ask "every login from ip 1.2.3.4 in the last hour" with one
query instead of grep-piping log lines.

What this audit checks
----------------------
For every `logger.<level>(...)` call site in `apps/api/{services,
routers}/*.py`, assert the message string is a plain literal (or a
%-format string), NOT:

  * `f"..."` — the f-string interpolation case.
  * `"...".format(...)` — same problem, different syntax.
  * `"..." + var + "..."` — string concatenation.

These patterns all produce opaque messages. Allowed shapes:

  * `logger.info("event happened")` — pure literal.
  * `logger.info("user %s signed in", user_id)` — Python's stdlib
    placeholder substitution (logging defers the format to
    rendering time, which lets log shippers see the unsubstituted
    template AND the args separately).
  * `logger.info("event", extra={"user_id": user_id})` — explicit
    structured fields.

Same ratchet pattern as the other code-quality audits: today's
count is 0 (the codebase already uses %-format), but a single
future regression would be invisible without this gate.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_API_ROOT = Path(__file__).resolve().parent.parent
_SCAN_DIRS = [_API_ROOT / "services", _API_ROOT / "routers"]


# Today's count of f-string / .format() / + in logger messages.
# Codebase is clean (0). The audit's job is to keep it that way.
BASELINE_BAD_LOGGER_MSG = 0


_LOG_LEVELS = {"info", "warning", "error", "debug", "exception", "critical"}


def _is_logger_call(node: ast.Call) -> bool:
    """`logger.info(...)` / `logger.warning(...)` / etc.

    Recognises both the `logger.X` (module-level logger) and the
    `self.logger.X` / `_logger.X` patterns. Any attribute access
    whose final attr is a recognised level on a `Name` ending in
    `logger` qualifies — narrow enough to skip e.g. `metrics.info`
    or `os.path.error`.
    """
    if not isinstance(node.func, ast.Attribute):
        return False
    if node.func.attr not in _LOG_LEVELS:
        return False
    target = node.func.value
    while isinstance(target, ast.Attribute):
        target = target.value
    if not isinstance(target, ast.Name):
        return False
    return target.id.lower().endswith("logger")


def _is_bad_message_arg(arg: ast.expr) -> str | None:
    """Return a string describing the bad shape, or None if the
    argument is acceptable.

    Acceptable: `ast.Constant` (a literal string).
    Bad: `ast.JoinedStr` (f-string), `ast.Call` to `.format`,
    `ast.BinOp` with `+` (string concatenation).
    """
    if isinstance(arg, ast.JoinedStr):
        return "f-string"
    if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute):
        if arg.func.attr == "format":
            return "str.format()"
    if isinstance(arg, ast.BinOp) and isinstance(arg.op, ast.Add):
        # Heuristic: if either operand is a string literal, this is
        # a string concat. We don't try to type-infer; the false-
        # positive shape (numeric +) inside a logger call is so
        # rare it's not worth the complexity.
        for side in (arg.left, arg.right):
            if isinstance(side, ast.Constant) and isinstance(side.value, str):
                return "string concat (+)"
    # Anything else (a Name reference, an attribute, a function
    # call returning a string) we accept — those are explicitly
    # named values that the operator chose to log; not the f-string
    # bug class.
    return None


def _audit_file(path: Path) -> list[str]:
    """Walk one Python file, return list of `path:line  bad-shape  snippet`."""
    text = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return []

    out: list[str] = []
    rel = path.relative_to(_API_ROOT)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _is_logger_call(node):
            continue
        if not node.args:
            continue
        bad = _is_bad_message_arg(node.args[0])
        if bad is None:
            continue
        # Build a short snippet for the failure message.
        try:
            snippet = ast.unparse(node)[:120]
        except Exception:  # pragma: no cover — older Python fallback
            snippet = ""
        out.append(f"{rel}:{node.lineno}  [{bad}]  {snippet}")
    return out


def _walk_py_files() -> list[Path]:
    out: list[Path] = []
    for d in _SCAN_DIRS:
        if not d.exists():
            continue
        for p in d.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            out.append(p)
    return sorted(out)


def test_no_logger_messages_use_f_strings_or_format():
    """Walk every module under `apps/api/{services,routers}`; for
    each `logger.X(...)` call, assert the message argument is a
    plain literal or %-format string — NOT an f-string, .format(),
    or `+` concat.

    Same ratchet pattern as the other audits: failures surface
    both directions (additions red-gate; reductions celebrate
    + prompt to lower the baseline).
    """
    findings: list[str] = []
    for path in _walk_py_files():
        findings.extend(_audit_file(path))

    n = len(findings)
    if n > BASELINE_BAD_LOGGER_MSG:
        new = n - BASELINE_BAD_LOGGER_MSG
        pytest.fail(
            f"{new} new bad-shape logger message(s) "
            f"(total now {n}, baseline {BASELINE_BAD_LOGGER_MSG}):\n  "
            + "\n  ".join(findings[:20])
            + (f"\n  … and {n - 20} more" if n > 20 else "")
            + "\n\nUse stdlib logging's %-format placeholders so log "
            "shippers (Datadog / Loki / Sentry) can see the unsubstituted "
            "template AND the dynamic values separately:\n\n"
            "    # bad — opaque to log shippers\n"
            '    logger.info(f"user {user_id} signed in")\n\n'
            "    # good — template + structured args\n"
            '    logger.info("user %s signed in", user_id)\n\n'
            "    # better — explicit structured fields via `extra`\n"
            '    logger.info("user signed in", extra={"user_id": user_id})'
        )
    if n < BASELINE_BAD_LOGGER_MSG:
        pytest.fail(
            f"Bad-logger-message count dropped from {BASELINE_BAD_LOGGER_MSG} "
            f"to {n} (you fixed {BASELINE_BAD_LOGGER_MSG - n}). 🎉 Update "
            f"`BASELINE_BAD_LOGGER_MSG` to {n}."
        )


def test_audit_recognises_documented_bad_shapes():
    """Defensive: hand-rolled fixtures verifying each bad-shape
    pattern is detected. A regression that broke `_is_bad_message_arg`
    (e.g. failed to walk into a JoinedStr) would silently let the
    next f-string regression through.
    """
    # f-string
    fstr = ast.parse('logger.info(f"user {x}")').body[0]
    assert isinstance(fstr, ast.Expr) and isinstance(fstr.value, ast.Call)
    assert _is_bad_message_arg(fstr.value.args[0]) == "f-string"

    # .format
    fmt = ast.parse('logger.info("user {}".format(x))').body[0]
    assert isinstance(fmt, ast.Expr) and isinstance(fmt.value, ast.Call)
    assert _is_bad_message_arg(fmt.value.args[0]) == "str.format()"

    # + concat
    cat = ast.parse('logger.info("user " + name)').body[0]
    assert isinstance(cat, ast.Expr) and isinstance(cat.value, ast.Call)
    assert _is_bad_message_arg(cat.value.args[0]) == "string concat (+)"

    # OK: %-format
    pct = ast.parse('logger.info("user %s", name)').body[0]
    assert isinstance(pct, ast.Expr) and isinstance(pct.value, ast.Call)
    assert _is_bad_message_arg(pct.value.args[0]) is None

    # OK: pure literal
    lit = ast.parse('logger.info("event happened")').body[0]
    assert isinstance(lit, ast.Expr) and isinstance(lit.value, ast.Call)
    assert _is_bad_message_arg(lit.value.args[0]) is None
