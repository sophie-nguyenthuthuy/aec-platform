"""HTTP status-code constants audit.

The bug class
-------------
Status codes as bare numeric literals are a low-grade readability
hazard with two real failure modes:

1. **Typo silently flips semantics.** `HTTPException(status_code=403)`
   when the author meant `401` looks fine on review — both are
   "auth-y." A future reader reading `403` may assume the route
   handles authorisation rather than authentication and add the
   wrong follow-up logic. Using `status.HTTP_403_FORBIDDEN` makes
   the intent explicit at the call site.

2. **Wrong code from copy-paste.** `405` (method not allowed) and
   `415` (unsupported media type) are easy to confuse mid-flight.
   `422` and `400` ditto. The constants encode their meaning so the
   reviewer doesn't have to remember the table.

Starlette / FastAPI already export `from starlette import status`.
The fix is universally one import + a search-replace.

What this audit checks
----------------------
AST walk over `apps/api/{routers,middleware,services}/*.py`. For
every keyword argument named `status_code` whose value is an
`ast.Constant` integer (and not the standard "no-content" 204 /
"created" 201 / "ok" 200 trinity, which are conventionally fine
inline), flag the call.

We also flag the positional shape `HTTPException(403, ...)` — same
bug, different syntax.

What's NOT checked
------------------
- Test files (`tests/**`) — assertions in tests like
  `assert resp.status_code == 404` are exempt: the test is
  precisely about the literal value.
- Constants in module-level docstrings or `Literal[...]` types
  (those are documentation, not call sites).
- The `200` / `201` / `204` literals — common decorator usage
  (`@router.post("/x", status_code=201)`) is allowed inline; the
  signal-to-noise on those is poor enough that requiring a
  constant doesn't help readability.

Same ratchet pattern as the other audits.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_API_ROOT = Path(__file__).resolve().parent.parent
_SCAN_DIRS = [
    _API_ROOT / "routers",
    _API_ROOT / "middleware",
    _API_ROOT / "services",
]


# Today's baseline. Filled in on first run.
BASELINE_LITERAL_STATUS_CODES = (
    43  # 2026-05: first-run baseline; ratchet down as call sites migrate to `status.HTTP_*` constants
)


# Codes we accept inline without forcing a constant. The
# decorator usage `@router.post("/x", status_code=201)` is
# idiomatic FastAPI and the conversion to
# `status.HTTP_201_CREATED` is more verbose than informative.
_ALLOWED_INLINE_LITERALS: frozenset[int] = frozenset({200, 201, 204})


# Per-(file, line) allowlist for legitimate cases. Each entry
# needs a stated reason. An empty rationale silences the gate.
ALLOWLIST: dict[tuple[str, int], str] = {
    # No entries today.
}


def _scan_files() -> list[Path]:
    out: list[Path] = []
    for d in _SCAN_DIRS:
        if not d.exists():
            continue
        for p in d.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            out.append(p)
    return sorted(out)


def _is_status_code_kwarg(kw: ast.keyword) -> bool:
    return kw.arg == "status_code"


def _is_http_exception_call(node: ast.Call) -> bool:
    """Match `HTTPException(...)` and `fastapi.HTTPException(...)` /
    `starlette.exceptions.HTTPException(...)`. We look at the
    rightmost name segment to keep it module-style-agnostic."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "HTTPException"
    if isinstance(func, ast.Attribute):
        return func.attr == "HTTPException"
    return False


def _audit_one_file(path: Path) -> list[str]:
    """Return offender strings of the form `path:line  preview`."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    rel = str(path.relative_to(_API_ROOT))
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return []
    findings: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        # Shape 1: `status_code=<int>` keyword anywhere — covers
        # FastAPI's `@router.post(..., status_code=403)`,
        # `JSONResponse(..., status_code=429)`, etc.
        for kw in node.keywords:
            if not _is_status_code_kwarg(kw):
                continue
            if not isinstance(kw.value, ast.Constant):
                continue
            value = kw.value.value
            if not isinstance(value, int):
                continue
            if value in _ALLOWED_INLINE_LITERALS:
                continue
            line = kw.value.lineno
            if (rel, line) in ALLOWLIST:
                continue
            findings.append(f"{rel}:{line}  status_code={value}")

        # Shape 2: `HTTPException(<int>, ...)` positional — older
        # idiom; first positional is `status_code`.
        if _is_http_exception_call(node) and node.args:
            first = node.args[0]
            if (
                isinstance(first, ast.Constant)
                and isinstance(first.value, int)
                and first.value not in _ALLOWED_INLINE_LITERALS
            ):
                line = first.lineno
                if (rel, line) in ALLOWLIST:
                    continue
                findings.append(f"{rel}:{line}  HTTPException({first.value}, …)")
    return findings


def _audit_all() -> list[str]:
    out: list[str] = []
    for path in _scan_files():
        out.extend(_audit_one_file(path))
    return out


def test_no_literal_http_status_codes():
    """Every non-trivial HTTP status code should be a `status.HTTP_*`
    constant, not a bare numeric literal.

    Failures surface both ratchet directions:
      * COUNT > BASELINE: a new bare literal landed. Replace with
        the matching `status.HTTP_*` constant
        (`from starlette import status` if not already imported).
      * COUNT < BASELINE: someone fixed one. 🎉 Update the
        baseline so future regressions can't silently rebuild back.
    """
    findings = _audit_all()
    n = len(findings)
    if n > BASELINE_LITERAL_STATUS_CODES:
        new = n - BASELINE_LITERAL_STATUS_CODES
        pytest.fail(
            f"{new} new literal HTTP status code(s) "
            f"(total now {n}, baseline {BASELINE_LITERAL_STATUS_CODES}):\n  "
            + "\n  ".join(findings[:20])
            + (f"\n  … and {n - 20} more" if n > 20 else "")
            + "\n\nReplace with the named constant:\n"
            "    from starlette import status\n"
            "    raise HTTPException(status.HTTP_403_FORBIDDEN, '…')\n\n"
            "Constants for the common ones:\n"
            "    400 -> HTTP_400_BAD_REQUEST\n"
            "    401 -> HTTP_401_UNAUTHORIZED\n"
            "    403 -> HTTP_403_FORBIDDEN\n"
            "    404 -> HTTP_404_NOT_FOUND\n"
            "    409 -> HTTP_409_CONFLICT\n"
            "    422 -> HTTP_422_UNPROCESSABLE_ENTITY\n"
            "    429 -> HTTP_429_TOO_MANY_REQUESTS\n"
            "    500 -> HTTP_500_INTERNAL_SERVER_ERROR\n"
            "    503 -> HTTP_503_SERVICE_UNAVAILABLE\n\n"
            "200/201/204 are intentionally allowed inline (the constant "
            "form is more verbose than informative for the happy path)."
        )
    if n < BASELINE_LITERAL_STATUS_CODES:
        pytest.fail(
            f"Literal-status-code count dropped from "
            f"{BASELINE_LITERAL_STATUS_CODES} to {n}. 🎉 Update "
            f"`BASELINE_LITERAL_STATUS_CODES` to {n}."
        )


def test_audit_recognises_documented_call_shapes():
    """Defensive: positive + negative AST fixtures. A regression in
    the walker would silently let bare-literal status codes through.
    """
    # Positive: `HTTPException(status_code=403)` — flagged.
    pos1 = ast.parse("from fastapi import HTTPException\nraise HTTPException(status_code=403, detail='no')\n")
    raise_stmt = pos1.body[1]
    assert isinstance(raise_stmt, ast.Raise)
    call = raise_stmt.exc
    assert isinstance(call, ast.Call)
    has_lit = any(
        kw.arg == "status_code"
        and isinstance(kw.value, ast.Constant)
        and isinstance(kw.value.value, int)
        and kw.value.value not in _ALLOWED_INLINE_LITERALS
        for kw in call.keywords
    )
    assert has_lit, "Audit missed status_code= keyword form"

    # Positive: `HTTPException(403, '...')` positional — flagged.
    pos2 = ast.parse("from fastapi import HTTPException\nraise HTTPException(403, 'no')\n")
    raise_stmt = pos2.body[1]
    assert isinstance(raise_stmt, ast.Raise)
    call = raise_stmt.exc
    assert isinstance(call, ast.Call)
    assert _is_http_exception_call(call)
    assert isinstance(call.args[0], ast.Constant) and call.args[0].value == 403, "Audit missed positional-arg form"

    # Negative: 200/201/204 — not flagged.
    neg = ast.parse('raise HTTPException(204, "no body")\n')
    raise_stmt = neg.body[0]
    assert isinstance(raise_stmt, ast.Raise)
    call = raise_stmt.exc
    assert isinstance(call, ast.Call)
    assert isinstance(call.args[0], ast.Constant) and call.args[0].value in _ALLOWED_INLINE_LITERALS

    # Negative: `status.HTTP_403_FORBIDDEN` — not flagged.
    neg2 = ast.parse("from starlette import status\nraise HTTPException(status.HTTP_403_FORBIDDEN, 'no')\n")
    raise_stmt = neg2.body[1]
    assert isinstance(raise_stmt, ast.Raise)
    call = raise_stmt.exc
    assert isinstance(call, ast.Call)
    # First arg is an Attribute, not a Constant — must NOT match.
    assert not isinstance(call.args[0], ast.Constant)


def test_allowlist_entries_actually_exist_in_source():
    """Defensive: stale ALLOWLIST entries silently mask future
    regressions. Every (path, line) tuple must correspond to a
    real call site under one of the scan roots.
    """
    if not ALLOWLIST:
        return  # nothing to check
    real_locations: set[tuple[str, int]] = set()
    for path in _scan_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        rel = str(path.relative_to(_API_ROOT))
        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if _is_status_code_kwarg(kw) and isinstance(kw.value, ast.Constant):
                    real_locations.add((rel, kw.value.lineno))
            if _is_http_exception_call(node) and node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, int):
                    real_locations.add((rel, first.lineno))
    stale = [k for k in ALLOWLIST if k not in real_locations]
    assert not stale, (
        f"Stale ALLOWLIST entries: {stale}. Remove them so the allowlist reflects only currently-live exemptions."
    )
