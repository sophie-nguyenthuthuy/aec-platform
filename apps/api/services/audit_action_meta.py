"""Audit action classifier (cycle Z2).

Pure helper for parsing the `audit_events.action` strings into
their `module.resource.verb` parts. Today the audit page's filter
chip grouping does this inline; future Slack-alert digests
grouped by module will need it; webhook event-type validation
depends on it.

Convention: actions follow the dotted form
`<module>.<resource>.<verb>`:

  * `costpulse.estimate.approve`
  * `pulse.change_order.approve`
  * `handover.package.deliver`

Two-segment exceptions (the `admin.*` actions):

  * `admin.normalizer_rule.create`  → 3 segments, module=admin
  * `admin.cron.run_now`            → 3 segments, module=admin

Single-segment / unstructured actions are a programmer error;
parser returns None for the resource + verb fields rather than
raising — the audit row still renders, it just doesn't group.

Pure Python — no DB, no `services.audit` import. The `AuditAction`
literal vocabulary lives over there; this module's job is to
classify whatever string lands in the column.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ActionParts:
    """Decomposed action string. `module` is always present (the
    parser uses an empty string for un-dotted input). `resource`
    and `verb` are optional — actions with only one segment past
    the module have `resource=None`."""

    module: str
    resource: str | None
    verb: str | None
    raw: str  # original, for round-trip / fallback


def parse_action(action: str | None) -> ActionParts:
    """Split an action string into module / resource / verb.

    Empty / None input returns an `ActionParts` with empty
    `module` so downstream code can branch without raising.

    Splitting rule (mirrors how the frontend ACTION_FILTERS
    interpret the strings):

      * `<a>.<b>.<c>` → module=a, resource=b, verb=c
      * `<a>.<b>`     → module=a, resource=None, verb=b
      * `<a>`         → module=a, resource=None, verb=None
      * `""` / None   → module="", resource=None, verb=None

    Unstructured (3+ dots) actions: the FIRST segment is the
    module, the LAST segment is the verb, everything between
    becomes the resource (joined by `.`). This handles the
    handful of `admin.normalizer_rule.create` style entries
    where `normalizer_rule` is itself two words.

    Defensive: returns ActionParts with the raw string preserved
    so even un-classifiable inputs round-trip through the audit
    page without losing the original text.
    """
    if not action:
        return ActionParts(module="", resource=None, verb=None, raw=action or "")
    parts = action.split(".")
    if len(parts) == 1:
        return ActionParts(module=parts[0], resource=None, verb=None, raw=action)
    if len(parts) == 2:
        # Two segments: `module.verb`. Resource is implicit (the
        # module IS the resource).
        return ActionParts(module=parts[0], resource=None, verb=parts[1], raw=action)
    # 3+ segments: first is module, last is verb, middle is resource.
    module = parts[0]
    verb = parts[-1]
    resource = ".".join(parts[1:-1])
    return ActionParts(module=module, resource=resource, verb=verb, raw=action)


def module_of(action: str | None) -> str:
    """Cheap accessor for just the module — most callers only
    need this for filter-chip grouping. Returns empty string for
    None / unstructured input.

    Pulled out as a function so call sites read naturally
    (`module_of(row.action)` instead of `parse_action(...).module`).
    """
    return parse_action(action).module


# Modules that surface in the audit page's "platform admin" filter
# group. These actions affect cross-tenant state (normalizer rules,
# manual cron runs, retention overrides, etc) and warrant separate
# visual treatment from per-tenant workflow actions.
ADMIN_MODULES: frozenset[str] = frozenset({"admin"})


def is_admin_action(action: str | None) -> bool:
    """True iff the action's module is in ADMIN_MODULES.

    Used by:
      * The audit page filter chips ("Platform admin" group).
      * Future Slack-alert digests (admin actions get a separate
        thread / channel — they're cross-tenant).
      * The audit CSV export's column-tone helper (admin actions
        render with the indigo-platform-admin tone, not the
        emerald approval tone).
    """
    return module_of(action) in ADMIN_MODULES


# ---------- Module catalog ----------
#
# Closed registry of modules that emit audit actions. Useful for
# the audit page filter dropdown — "show me all events from one
# module" without enumerating every action.
#
# Adding a new module: also add a new `AuditAction` literal entry
# in `services/audit.py` and a frontend label in the audit page's
# ACTION_FILTERS list. The integrator-surface snapshot pins the
# webhook event_catalog ⊆ AuditAction relationship; this set is
# the operator-facing grouping above that.


AUDIT_MODULES: frozenset[str] = frozenset(
    {
        "costpulse",
        "pulse",
        "org",
        "notifications",
        "handover",
        "punchlist",
        "submittals",
        "admin",
        "webhooks",
    }
)


def is_known_module(action: str | None) -> bool:
    """True iff the action's module is in `AUDIT_MODULES`. The
    audit page renders unknown modules in a fallback "Other"
    group — pin so an action with a typo'd module surfaces
    visibly rather than silently slotting into the empty Other
    group."""
    return module_of(action) in AUDIT_MODULES
