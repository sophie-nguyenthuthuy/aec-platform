"""Static check: every `AuditAction` Literal entry has a dropdown
option on the frontend `/settings/audit` page.

Why this test exists: this batch caught that the audit page's
`ACTION_FILTERS` list had drifted from `services.audit.AuditAction`
— ~10 of the 18 actions had no dropdown entry, so admins couldn't
filter to them even though the rows landed in the table. The
existing `audit_log` UI is the only surface that lets admins query
audit history, so a missing dropdown entry equals "this verb is
silently invisible to filters."

Caught at CI: same shape as `test_apifetch_routes_match.py` —
walk the frontend, parse a closed-set list, assert every Literal
entry on the API side appears.

Allowlist: `_TOLERATED` for actions that intentionally don't get a
dropdown (e.g. internal system events ops shouldn't filter to).
Empty by design — a non-empty entry should carry a TODO + reason.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import get_args

# AuditAction entries that intentionally don't surface in the UI
# dropdown. Empty until proven otherwise — silent invisibility is
# worse than a too-long dropdown.
_TOLERATED: set[str] = set()


def _project_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "apps" / "web").is_dir():
            return parent
    raise RuntimeError("could not locate repo root from test file")


def _audit_page_action_filter_values(repo_root: Path) -> set[str]:
    """Parse the audit page TSX for the dropdown's action `value`s.

    Two shapes are accepted because the page's constant shape has
    flipped between batches:

      * `ACTION_FILTER_VALUES: readonly string[] = [...]`
        (post-i18n: labels live in next-intl bundles)
      * `ACTION_FILTERS: Array<{ value, label }> = [
            { value: "...", label: "..." }, ...
        ]` (pre-i18n: labels inline)

    Either way the *set of action verbs* is what the dropdown drives,
    and that's what the sync check cares about. A regex that matches
    a bare quoted-string list AND a `value: "..."` field covers both.
    """
    src = repo_root / "apps" / "web" / "app" / "(dashboard)" / "settings" / "audit" / "page.tsx"
    text = src.read_text(encoding="utf-8")

    # Try the post-i18n form first (preferred). Fall back to the
    # pre-i18n `ACTION_FILTERS` array of objects.
    m = re.search(r"ACTION_FILTER_VALUES:[^=]*=\s*\[(.+?)\];", text, re.DOTALL)
    if m is not None:
        body = m.group(1)
        # Strip comments so quoted strings inside don't pollute the
        # value set.
        body = re.sub(r"//.*?$", "", body, flags=re.MULTILINE)
        body = re.sub(r"/\*.*?\*/", "", body, flags=re.DOTALL)
        return set(re.findall(r'"([^"]*)"', body))

    m = re.search(r"ACTION_FILTERS:[^=]*=\s*\[(.+?)\];", text, re.DOTALL)
    assert m, "could not locate ACTION_FILTER_VALUES or ACTION_FILTERS in audit page.tsx"
    body = m.group(1)
    # Each entry shape: `{ value: "...", label: "..." }` — pull only
    # the `value:` strings, not the labels.
    return set(re.findall(r'value:\s*"([^"]*)"', body))


def test_every_audit_action_appears_in_audit_page_filters():
    """Every `AuditAction` Literal entry must have an `ACTION_FILTERS`
    dropdown option on `/settings/audit`. Otherwise admins can't
    filter to it and the audit page is a partial-coverage view of
    the table.

    This catches the same drift class as `test_apifetch_routes_match`
    — frontend lists that sync against an API-side source of truth.
    """
    from services.audit import AuditAction

    repo_root = _project_root()
    fe_values = _audit_page_action_filter_values(repo_root)
    audit_actions = set(get_args(AuditAction))

    missing = audit_actions - fe_values - _TOLERATED
    assert not missing, (
        "These `AuditAction` Literal entries are NOT in the "
        "/settings/audit page's `ACTION_FILTERS` dropdown — admins "
        "won't be able to filter to them. Add the entry to "
        "`apps/web/app/(dashboard)/settings/audit/page.tsx`, or (last "
        "resort) add to `_TOLERATED` here with a TODO + reason. "
        f"Missing: {sorted(missing)}"
    )


def test_audit_page_filters_set_is_non_empty():
    """Sanity: if `ACTION_FILTERS` collapsed to nothing (e.g. moved
    to a different file), the subset check would pass vacuously."""
    repo_root = _project_root()
    fe_values = _audit_page_action_filter_values(repo_root)
    # 1 sentinel ("") + at least the 5 most common audit actions.
    assert len(fe_values) >= 5
