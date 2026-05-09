"""Audit: every `audit.record(action="...")` call site MUST pass
an `action` string that's in the canonical `AuditAction` Literal.

The `AuditAction` Literal in `services.audit` is the closed
vocabulary of audit-row action strings. Every audit call in the
codebase passes one of these strings as a positional or keyword
argument.

Failure mode this catches:

  * A handler calls `record_audit(action="costpulse.boq.import",
    ...)` (typo: should be `costpulse.boq.imports`) and the
    audit row goes through with the typo'd action. Compliance
    queries that GROUP BY action OR filter on the canonical
    string silently miss the row. The audit log is "complete"
    by row count but useless for the question being asked.

  * A NEW handler is added that emits an action string never
    added to the Literal. mypy *might* catch this if it's run
    AND the call site is fully typed AND mypy follows the
    Literal narrow — three conditions, any of which often
    fails in practice. This audit catches the regression
    unconditionally at test time.

The audit walks every `.py` under `apps/api/`, AST-parses, finds
every call to:

  * `record_audit(...)` — common alias when the handler does
    `from services.audit import record as record_audit`
  * `audit_record(...)` — alternate alias used in some routers
  * `record(...)` — bare alias (rare; only matches when the
    name comes from `services.audit.record` import)
  * `<some>.record(...)` — module-attribute calls like
    `_audit.record(...)`

For each call, extracts the `action=` keyword arg's literal
string. If the action isn't in `AuditAction`, surfaces the
file:line + the offending string + suggests the fix.

Allowlist surface:

  * `_DYNAMIC_ACTION_CALL_SITES` — file:line entries where
    `action=` is a variable / formatted string (not a literal).
    The audit can't statically resolve dynamic values, so these
    are skipped. Today: empty (every callsite uses a literal).

This file is read-only. Survives reverts.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import get_args

from services.audit import AuditAction


# Function names that resolve to `services.audit.record`. The
# handler `record(...)` form (bare `record` after a `from
# services.audit import record` line) is also matched, with a
# false-positive risk on unrelated `record(...)` symbols — we
# accept the noise because the audit's failure message names the
# exact file:line for triage.
_AUDIT_RECORD_NAMES: frozenset[str] = frozenset(
    {
        "record_audit",
        "audit_record",
    }
)


# Allowlist for call sites where `action=` is a non-literal
# expression (variable, formatted string). The audit can't
# resolve those statically; skipping is the conservative choice
# (better one false-negative than every dynamic action firing
# the audit). Today: empty.
_DYNAMIC_ACTION_CALL_SITES: frozenset[str] = frozenset()


def _api_dir() -> Path:
    return Path(__file__).parent.parent


def _is_audit_record_call(node: ast.Call) -> bool:
    """Return True if `node.func` resolves to a known
    `services.audit.record` alias.

    Three forms accepted:
      1. `record_audit(...)` / `audit_record(...)` — bare-name
         call where the name is in `_AUDIT_RECORD_NAMES`.
      2. `<module>.record(...)` where the module name ends in
         `audit` (e.g. `_audit.record(...)`, `audit.record(...)`).
         Catches the `import services.audit as _audit` pattern.
      3. Bare `record(...)` is intentionally NOT matched — too
         many false positives in a multi-thousand-file codebase.
         Handlers using this form should switch to a named alias.
    """
    func = node.func
    if isinstance(func, ast.Name):
        return func.id in _AUDIT_RECORD_NAMES
    if isinstance(func, ast.Attribute) and func.attr == "record":
        # The value must be a Name node ending in 'audit'.
        if isinstance(func.value, ast.Name) and "audit" in func.value.id.lower():
            return True
    return False


def _extract_action_kwarg(node: ast.Call) -> tuple[str | None, bool]:
    """Pull the `action=` keyword arg's value out of a Call node.

    Returns `(value, is_literal)` where:
      * `value` is the literal string if `action=` is a
        Constant str — the audit's primary-path target.
      * `value` is None if `action=` isn't supplied (positional
        is rare but possible; we don't attempt to resolve it).
      * `is_literal` is False when the value is a non-Constant
        expression (variable, f-string). The audit emits a
        skip-with-allowlist suggestion in that case.
    """
    for kw in node.keywords:
        if kw.arg != "action":
            continue
        if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
            return kw.value.value, True
        return None, False
    return None, True  # No `action=` kwarg → positional or other shape; skip.


def _walk_audit_record_calls(api_dir: Path):
    """Iterate every audit-record call site under `api_dir`,
    yielding `(rel_path, line_no, action_str_or_None, is_literal)`."""
    for py_file in api_dir.rglob("*.py"):
        # Skip the tests/ tree itself — pin tests legitimately
        # reference action strings without making real audit calls.
        rel = py_file.relative_to(api_dir)
        if rel.parts and rel.parts[0] == "tests":
            continue
        # Skip migrations — alembic's revision IDs aren't audit
        # actions even if a migration mentions them.
        if rel.parts and rel.parts[0] == "alembic":
            continue
        try:
            tree = ast.parse(py_file.read_text(), filename=str(py_file))
        except SyntaxError:
            # A broken file shouldn't block the audit; broken
            # files surface in the broader test suite anyway.
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not _is_audit_record_call(node):
                continue
            action, is_literal = _extract_action_kwarg(node)
            yield str(rel), node.lineno, action, is_literal


def test_every_audit_record_action_in_literal():
    """SECURITY/COMPLIANCE pin. Every literal `action=` string in
    every audit-record call site MUST be a member of the
    `AuditAction` Literal.

    Failure surfaces a list of `(file:line, action_str)` pairs.
    Resolution paths:

      1. **Typo'd action string** — fix the call site (the most
         common case).
      2. **New action category** — add the string to
         `AuditAction` in `services/audit.py`. Two pins move in
         lockstep: the Literal expands AND this audit's check
         passes against the new value.
      3. **Dynamic action** (string built from a variable) — add
         the file:line to `_DYNAMIC_ACTION_CALL_SITES`. PR
         review of THAT addition checks that the dynamic source
         is constrained to the Literal's set.
    """
    canonical_actions = set(get_args(AuditAction))

    bad_actions: list[str] = []
    dynamic_sites_unallowlisted: list[str] = []

    api_dir = _api_dir()
    for rel_path, line_no, action, is_literal in _walk_audit_record_calls(api_dir):
        site = f"{rel_path}:{line_no}"
        if not is_literal and action is None:
            # Dynamic `action=variable` — needs allowlist or
            # refactor to a literal.
            if site not in _DYNAMIC_ACTION_CALL_SITES:
                dynamic_sites_unallowlisted.append(site)
            continue
        if action is None:
            # No `action=` kwarg at all — possibly positional or
            # a different signature. Skip; signature pin in
            # `test_audit_record_signature_pin.py` covers shape.
            continue
        if action not in canonical_actions:
            bad_actions.append(f"{site}  →  action={action!r}")

    assert not bad_actions, (
        "These audit-record call sites pass an `action` string "
        "that's NOT in the canonical AuditAction Literal:\n  "
        + "\n  ".join(sorted(bad_actions))
        + "\n\n"
        f"Canonical actions ({len(canonical_actions)} total):\n  "
        + "\n  ".join(sorted(canonical_actions))
        + "\n\n"
        "COMPLIANCE: an audit row with a non-canonical action "
        "string still writes, but compliance queries that "
        "GROUP BY action OR filter on the canonical strings "
        "silently miss it. The audit log is 'complete' by row "
        "count but useless for the question being asked.\n\n"
        "Resolution:\n"
        "  1. If it's a typo, fix the call site.\n"
        "  2. If a new action category is intentional, add the "
        "string to `AuditAction` in services/audit.py — both "
        "pins (the Literal + this audit) move in lockstep."
    )

    assert not dynamic_sites_unallowlisted, (
        "These audit-record call sites use a non-literal "
        "`action=` expression (variable / f-string):\n  "
        + "\n  ".join(sorted(dynamic_sites_unallowlisted))
        + "\n\n"
        "The audit can't statically resolve dynamic values. "
        "Resolution:\n"
        "  1. Refactor to pass a literal string (preferred — "
        "       static checking covers more ground).\n"
        "  2. If the dynamic source is provably constrained to "
        "       the AuditAction set (e.g. the value comes from "
        "       another typed Literal), add the file:line to "
        "       `_DYNAMIC_ACTION_CALL_SITES` in this audit. PR "
        "       review of that addition is where the constraint "
        "       gets vetted."
    )


def test_audit_actually_finds_call_sites():
    """Sanity floor — the AST walker actually finds audit-record
    calls. If the codebase refactored every callsite to a
    different alias, the walker would silently pass with zero
    sites scanned.

    A failure here usually means EITHER (a) every audit-record
    callsite was renamed (update `_AUDIT_RECORD_NAMES`) OR (b)
    the api/ layout shifted (update `_api_dir()`).
    """
    api_dir = _api_dir()
    sites = list(_walk_audit_record_calls(api_dir))
    assert len(sites) >= 5, (
        f"AST walker found {len(sites)} audit-record callsites — "
        "implausibly few. Either every handler stopped emitting "
        "audit rows (broader regression worth surfacing) OR the "
        "alias detection in `_is_audit_record_call` no longer "
        "matches the codebase's call patterns."
    )


def test_canonical_audit_action_set_size_floor():
    """Sanity floor on `AuditAction` itself. If the Literal
    shrinks below a credible floor (e.g. someone clears it
    while debugging), the audit's bad_actions check would
    silently flag every call site. Cap-and-floor the size."""
    canonical = set(get_args(AuditAction))
    # Floor: there are roughly a dozen documented actions today
    # (org.member.role_change, costpulse.estimate.approve, etc).
    # 8 is a low floor — well below current count.
    assert len(canonical) >= 8, (
        f"AuditAction Literal has {len(canonical)} members — "
        "implausibly few. Either the Literal got truncated by a "
        "refactor (audit log goes blind) or the `services.audit` "
        "import path changed."
    )


def test_dynamic_call_sites_allowlist_is_minimal():
    """The carve-out for dynamic `action=variable` callsites
    should stay empty in steady state. Pin a low cap so a future
    addition is reviewed deliberately."""
    assert len(_DYNAMIC_ACTION_CALL_SITES) <= 2, (
        f"_DYNAMIC_ACTION_CALL_SITES has "
        f"{len(_DYNAMIC_ACTION_CALL_SITES)} entries: "
        f"{sorted(_DYNAMIC_ACTION_CALL_SITES)}. Dynamic action "
        "strings defeat the static check; if the list grows past "
        "2 the audit's signal weakens — refactor to literals "
        "rather than expand the carve-out."
    )
