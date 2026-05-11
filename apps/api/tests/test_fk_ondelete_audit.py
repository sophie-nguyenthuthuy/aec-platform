"""Foreign-key ON DELETE behaviour audit.

The bug class
-------------
A migration declares:

    sa.Column(
        "owner_id",
        postgresql.UUID,
        sa.ForeignKey("users.id"),  # <-- no `ondelete=`
    )

Postgres' default behaviour with no `ON DELETE` clause is `NO ACTION`
— the delete is REJECTED at runtime if any child row references the
parent. That's almost never what we actually want:

  * For tenant-scoped child rows (org_id, project_id, etc.):
    `ON DELETE CASCADE` is right. When the org goes away, take the
    children with it.
  * For attribution columns (created_by, assignee_id):
    `ON DELETE SET NULL` is right. The user leaves the platform; the
    audit trail of what they did SHOULD survive without their name.
  * For governance / referential integrity (audit log, billing):
    `ON DELETE RESTRICT` (= NO ACTION but explicit) is right. Don't
    let the parent disappear while a child still depends on it.

What this audit catches
-----------------------
Every `sa.ForeignKey(...)` and `op.create_foreign_key(...)` call
across `apps/api/alembic/versions/*.py` must have an explicit
`ondelete=` keyword. The audit doesn't enforce WHICH choice — that's
a per-FK design call — only that the choice was MADE rather than
left to NO ACTION by default.

Implementation
--------------
AST walk. Same shape as `test_migration_safety_audit.py`. Recognises
both forms:
  * `sa.ForeignKey("table.col", ondelete="...")`
  * `op.create_foreign_key("name", "src", "dst", [...], [...], ondelete="...")`
Plus an optional `# fk-ondelete: <reason>` inline comment that
documents why no clause is needed (very rare — usually appropriate
for system-managed link tables that get manually pruned via cron).

Same ratchet pattern as the other infrastructure audits.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_API_ROOT = Path(__file__).resolve().parent.parent
_VERSIONS_DIR = _API_ROOT / "alembic" / "versions"


# Today's baseline: filled in on first run. The audit identifies
# every FK without an explicit `ondelete=`. Ratchet down as each
# gets fixed.
BASELINE_FK_NO_ONDELETE = 0


def _list_migration_files() -> list[Path]:
    return sorted(p for p in _VERSIONS_DIR.glob("*.py") if p.name != "__init__.py" and p.is_file())


def _comment_lines_with_marker(text: str, marker: str) -> set[int]:
    """1-indexed line numbers carrying `marker` in a comment.
    Returns the line itself + the line below — covers a comment
    above a multi-line call.
    """
    out: set[int] = set()
    for i, line in enumerate(text.splitlines(), start=1):
        if marker in line:
            out.add(i)
            out.add(i + 1)
    return out


def _kw(call: ast.Call, name: str) -> ast.expr | None:
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


def _is_foreign_key_call(call: ast.Call) -> bool:
    """`sa.ForeignKey(...)` (constructor call). Recognises both
    `sa.ForeignKey` (the dominant form) and bare `ForeignKey` if
    imported directly."""
    func = call.func
    # `sa.ForeignKey(...)` → Attribute(attr='ForeignKey')
    if isinstance(func, ast.Attribute) and func.attr == "ForeignKey":
        return True
    # `ForeignKey(...)` (rare in our codebase but possible)
    if isinstance(func, ast.Name) and func.id == "ForeignKey":
        return True
    return False


def _is_create_foreign_key_call(call: ast.Call) -> bool:
    """`op.create_foreign_key(...)` migration helper."""
    func = call.func
    return isinstance(func, ast.Attribute) and func.attr == "create_foreign_key"


def _has_ondelete(call: ast.Call) -> bool:
    val = _kw(call, "ondelete")
    if val is None:
        return False
    # Accept any non-empty string literal. Could be CASCADE, SET NULL,
    # SET DEFAULT, RESTRICT, NO ACTION (explicit).
    if isinstance(val, ast.Constant) and isinstance(val.value, str) and val.value.strip():
        return True
    # Non-literal expressions (a constant ref, a conditional) — accept
    # them too; the developer made an explicit choice even if the
    # value isn't statically resolvable here.
    return True


def _audit_one_file(path: Path) -> list[str]:
    """Return list of `path:line  <fk-target>` for FKs missing ondelete."""
    text = path.read_text(encoding="utf-8")
    safety_lines = _comment_lines_with_marker(text, "# fk-ondelete:")
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return []

    out: list[str] = []
    rel = path.relative_to(_API_ROOT)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _is_foreign_key_call(node) or _is_create_foreign_key_call(node):
            if node.lineno in safety_lines:
                continue
            if _has_ondelete(node):
                continue
            # Build a short label naming the FK target if available.
            target = "?"
            if node.args and isinstance(node.args[0], ast.Constant):
                if isinstance(node.args[0].value, str):
                    target = node.args[0].value
            out.append(f"{rel}:{node.lineno}  ForeignKey({target!r}) — no ondelete=")
    return out


def test_every_foreign_key_has_explicit_ondelete():
    """Walk every alembic revision file; for each `sa.ForeignKey(...)`
    or `op.create_foreign_key(...)` call, assert `ondelete=` is set.

    Failures surface both ratchet directions. The fix per offender is
    one of:
      * `ondelete="CASCADE"` for tenant-scoped child rows.
      * `ondelete="SET NULL"` for attribution columns (created_by,
        assignee_id) where the row should outlive the user.
      * `ondelete="RESTRICT"` for governance / referential integrity
        (audit log, billing-related tables) where the parent must
        outlive every child.
      * A `# fk-ondelete: <reason>` comment if the default
        `NO ACTION` is genuinely the right choice for this FK.
    """
    findings: list[str] = []
    for path in _list_migration_files():
        findings.extend(_audit_one_file(path))

    n = len(findings)
    if n > BASELINE_FK_NO_ONDELETE:
        new = n - BASELINE_FK_NO_ONDELETE
        pytest.fail(
            f"{new} new ForeignKey(...) call(s) without explicit "
            f"ondelete= (total now {n}, baseline {BASELINE_FK_NO_ONDELETE}):\n  "
            + "\n  ".join(findings[:20])
            + (f"\n  … and {n - 20} more" if n > 20 else "")
            + "\n\nPostgres defaults missing-ondelete to NO ACTION, which "
            "rejects the delete at runtime if any child row references "
            "the parent. The right answer is one of:\n"
            "  • CASCADE   — for tenant-scoped child rows\n"
            "  • SET NULL  — for attribution columns (created_by, etc.)\n"
            "  • RESTRICT  — for governance / billing referential integrity\n\n"
            "If NO ACTION is genuinely right (rare), add a "
            "`# fk-ondelete: <reason>` comment above the FK."
        )
    if n < BASELINE_FK_NO_ONDELETE:
        pytest.fail(
            f"FK-without-ondelete count dropped from {BASELINE_FK_NO_ONDELETE} "
            f"to {n}. 🎉 Update `BASELINE_FK_NO_ONDELETE` to {n}."
        )


def test_audit_recognises_documented_fk_call_shapes():
    """Defensive: hand-rolled fixtures verifying the AST walker
    detects each FK form. Without this, a regression that broke
    `_is_foreign_key_call` (e.g. failing on `sa.ForeignKey` after
    a refactor renamed the import) would silently let unguarded
    FKs through.
    """
    # sa.ForeignKey with ondelete → safe.
    safe1 = ast.parse("import sqlalchemy as sa\nx = sa.ForeignKey('users.id', ondelete='CASCADE')\n")
    for node in ast.walk(safe1):
        if isinstance(node, ast.Call) and _is_foreign_key_call(node):
            assert _has_ondelete(node)

    # sa.ForeignKey without ondelete → unsafe.
    unsafe1 = ast.parse("import sqlalchemy as sa\nx = sa.ForeignKey('users.id')\n")
    found_unsafe = False
    for node in ast.walk(unsafe1):
        if isinstance(node, ast.Call) and _is_foreign_key_call(node):
            assert not _has_ondelete(node)
            found_unsafe = True
    assert found_unsafe, "sa.ForeignKey not detected as a FK call"

    # op.create_foreign_key with ondelete → safe.
    safe2 = ast.parse(
        "from alembic import op\nop.create_foreign_key('fk', 'tasks', 'users', ['x'], ['id'], ondelete='SET NULL')\n"
    )
    for node in ast.walk(safe2):
        if isinstance(node, ast.Call) and _is_create_foreign_key_call(node):
            assert _has_ondelete(node)
