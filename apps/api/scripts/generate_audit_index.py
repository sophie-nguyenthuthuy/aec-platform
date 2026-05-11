"""Generate `docs/audit-suite.md` from every `tests/test_*_audit.py`.

Each audit's first paragraph (the "bug class" preamble) becomes its
entry's prose; every `BASELINE_*` constant becomes a row in the
ratchet table. Run via `python -m scripts.generate_audit_index`.

The doc itself is checked into git so reviewers + new contributors
have a single page to scan instead of grepping for `_audit.py`. The
generator is the source of truth — re-run it whenever an audit
lands or a baseline ratchets, then commit the regenerated doc.

This script is intentionally simple AST-only: it doesn't import any
audit (avoiding the heavy FastAPI/SQLAlchemy load) and doesn't
execute the BASELINE_* expressions (just reads their literal RHS).
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

_API_ROOT = Path(__file__).resolve().parent.parent
_TESTS = _API_ROOT / "tests"
_REPO_ROOT = _API_ROOT.parent.parent
_OUTPUT = _REPO_ROOT / "docs" / "audit-suite.md"


def _audit_files() -> list[Path]:
    return sorted(_TESTS.glob("test_*_audit.py"))


def _first_paragraph(docstring: str) -> str:
    """First paragraph (text before the first blank line). Strips
    any markdown-style header underlines (`-----`) the docstring may
    use."""
    if not docstring:
        return ""
    lines: list[str] = []
    for line in docstring.splitlines():
        stripped = line.strip()
        if not stripped:
            if lines:
                break
            continue
        # Skip markdown ASCII underlines like `-------` / `=======`.
        if set(stripped) <= {"-", "="}:
            continue
        lines.append(stripped)
    return " ".join(lines)


_BASELINE_RE = re.compile(r"^(BASELINE_[A-Z0-9_]+)\s*=\s*(.+?)(?:\s*#.*)?$")


def _baselines(tree: ast.Module) -> list[tuple[str, str]]:
    """Return `[(name, value_repr), ...]` for every module-level
    `BASELINE_*` assignment. Reads the literal source rather than
    evaluating it — keeps the generator hermetic."""
    out: list[tuple[str, str]] = []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        name = node.targets[0].id
        if not name.startswith("BASELINE_"):
            continue
        # Use ast.unparse for a stable repr regardless of the
        # original literal style.
        try:
            value = ast.unparse(node.value)
        except Exception:  # noqa: BLE001
            value = "<unparseable>"
        out.append((name, value))
    return out


def _test_names(tree: ast.Module) -> list[str]:
    """Top-level `def test_*` function names. Lets the index point a
    reader at the specific assertion to read."""
    out: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_"):
                out.append(node.name)
    return out


def _slug(name: str) -> str:
    """`test_cron_mutex_audit.py` → `cron-mutex`. Used for the
    table-of-contents anchors."""
    stem = name.removesuffix(".py").removeprefix("test_").removesuffix("_audit")
    return stem.replace("_", "-")


def _humanise(name: str) -> str:
    """`test_cron_mutex_audit.py` → `Cron mutex`. Title-case for the
    section header."""
    stem = name.removesuffix(".py").removeprefix("test_").removesuffix("_audit")
    return stem.replace("_", " ").capitalize()


def _render(audits: list[Path]) -> str:
    parts: list[str] = []
    parts.append("# Ratchet audit suite\n")
    parts.append(
        "<!-- GENERATED FILE — do not edit by hand. Regenerate via "
        "`python -m scripts.generate_audit_index` from `apps/api/`. "
        "Source of truth is each `tests/test_*_audit.py` docstring + "
        "its `BASELINE_*` constants. -->\n"
    )
    parts.append(
        "Each entry below is a ratchet test in `apps/api/tests/`. The "
        "audit walks a chunk of the codebase, counts a specific "
        "bug-shape, and asserts the count hasn't grown beyond a pinned "
        "baseline. Reductions ALSO fail (with a 🎉) so a baseline drop "
        "is captured in the same PR as the fix.\n"
    )
    parts.append(
        "Run all of them with `make audit` (~5s). They also run as a "
        "pre-commit hook (`ratchet-audits`) scoped to files any audit "
        "scans, and inside the broader `pytest` CI job.\n"
    )
    parts.append("## Index\n")
    for path in audits:
        slug = _slug(path.name)
        title = _humanise(path.name)
        parts.append(f"- [{title}](#{slug})")
    parts.append("")

    for path in audits:
        slug = _slug(path.name)
        title = _humanise(path.name)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as e:
            parts.append(f'## {title} <a id="{slug}"></a>\n')
            parts.append(f"_Could not parse: {e}_\n")
            continue

        first = _first_paragraph(ast.get_docstring(tree) or "")
        baselines = _baselines(tree)
        tests = _test_names(tree)

        parts.append(f'## {title} <a id="{slug}"></a>')
        parts.append(f"_File:_ `apps/api/tests/{path.name}`\n")
        if first:
            parts.append(first + "\n")
        if baselines:
            parts.append("**Baselines**:\n")
            parts.append("| Constant | Value |")
            parts.append("|---|---|")
            for name, value in baselines:
                parts.append(f"| `{name}` | `{value}` |")
            parts.append("")
        if tests:
            parts.append("**Tests**: " + ", ".join(f"`{t}`" for t in tests))
            parts.append("")

    return "\n".join(parts).rstrip() + "\n"


def main() -> int:
    audits = _audit_files()
    if not audits:
        print("no audits found under tests/", file=sys.stderr)
        return 1
    text = _render(audits)
    _OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    _OUTPUT.write_text(text, encoding="utf-8")
    print(f"wrote {_OUTPUT.relative_to(_REPO_ROOT)} ({len(audits)} audits)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
