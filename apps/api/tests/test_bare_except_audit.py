"""Bare `except:` audit.

The bug class
-------------
A bare `except:` catches everything — `Exception`,
`KeyboardInterrupt`, `SystemExit`, `GeneratorExit`. It silently
swallows operator Ctrl-C and shutdown signals:

    while True:
        try:
            do_work()
        except:           # <-- catches Ctrl-C, ignores it
            pass

Operators expect Ctrl-C to break the loop. With the bare except,
the signal is caught and discarded; the only way out is `kill -9`.

Same shape silently swallows `SystemExit` from `sys.exit()`,
turning intended graceful shutdowns into hangs.

Fix: catch `Exception` explicitly. `BaseException` (the only
broader option) is almost never what you want — exit + interrupt
+ generator-cleanup signals should propagate.

Ruff catches this via E722. This ratchet survives ruff config
drift — same defensive pattern as the noqa/type-ignore audits.

What this audit checks
----------------------
AST walk over `apps/api/{core,db,middleware,models,routers,
schemas,services,workers}/*.py` plus `apps/worker/*.py`. Flag
every `ast.ExceptHandler` whose `type` is None.

What's NOT checked
------------------
- `except Exception:` — explicit; passes.
- `except (TypeError, ValueError):` — explicit; passes.
- `except KeyboardInterrupt:` — explicit and unusual but valid.
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
BASELINE_BARE_EXCEPT = 0


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
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if node.type is not None:
            continue
        line = node.lineno
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


def test_no_bare_except_clauses():
    """Every `except:` should explicitly name what it catches —
    typically `Exception`, sometimes a specific subclass.
    """
    findings = _audit_all()
    n = len(findings)
    if n > BASELINE_BARE_EXCEPT:
        new = n - BASELINE_BARE_EXCEPT
        pytest.fail(
            f"{new} new bare `except:` clause(s) "
            f"(total now {n}, baseline {BASELINE_BARE_EXCEPT}):\n  "
            + "\n  ".join(findings[:20])
            + (f"\n  … and {n - 20} more" if n > 20 else "")
            + "\n\nReplace with the explicit class:\n"
            "    # was:\n"
            "    try:\n"
            "        risky()\n"
            "    except:\n"
            "        ...\n"
            "    # use:\n"
            "    try:\n"
            "        risky()\n"
            "    except Exception:  # noqa: BLE001 if you really mean it\n"
            "        ...\n\n"
            "A bare except catches BaseException — including "
            "KeyboardInterrupt and SystemExit. Operators' Ctrl-C "
            "is silently swallowed; sys.exit() hangs. Catch "
            "Exception explicitly so signals propagate."
        )
    if n < BASELINE_BARE_EXCEPT:
        pytest.fail(
            f"Bare-except count dropped from {BASELINE_BARE_EXCEPT} "
            f"to {n}. 🎉 Update `BASELINE_BARE_EXCEPT` to {n}."
        )


def test_audit_recognises_documented_shapes():
    """Defensive: positive + negative AST fixtures."""
    # Positive: bare except.
    pos = ast.parse(
        "def f():\n"
        "    try:\n"
        "        x = 1\n"
        "    except:\n"
        "        pass\n"
    )
    bares = [
        n for n in ast.walk(pos)
        if isinstance(n, ast.ExceptHandler) and n.type is None
    ]
    assert len(bares) == 1

    # Negative: except Exception.
    neg = ast.parse(
        "def g():\n"
        "    try:\n"
        "        x = 1\n"
        "    except Exception:\n"
        "        pass\n"
    )
    bares = [
        n for n in ast.walk(neg)
        if isinstance(n, ast.ExceptHandler) and n.type is None
    ]
    assert bares == []

    # Negative: except (A, B).
    neg2 = ast.parse(
        "def h():\n"
        "    try:\n"
        "        x = 1\n"
        "    except (TypeError, ValueError):\n"
        "        pass\n"
    )
    bares = [
        n for n in ast.walk(neg2)
        if isinstance(n, ast.ExceptHandler) and n.type is None
    ]
    assert bares == []
