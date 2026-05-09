"""Audit: Pydantic *input* schemas (Create / Update / Patch /
Payload) MUST NOT accept `organization_id` from the client.

Cross-tenant attribution prevention. The pattern this audit
enforces:

  * **Output schemas** (`*Out`, `*Detail`, `*Response`, `*Read`)
    MAY include `organization_id` — that's how the API tells the
    client which tenant a row belongs to. Legitimate.

  * **Input schemas** (`*Create`, `*Update`, `*Patch`, `*Payload`)
    MUST NOT include `organization_id` — the tenant comes from
    `auth.organization_id` in the route handler, NOT from the
    request body. A regression that added the field to an
    input schema would let a partner mint resources against
    another tenant by overriding the org id in the body.

This is the same threat model as the `AdminSessionFactory`
audit but at a different layer: BYPASSRLS-via-session vs
BYPASSRLS-via-payload-attribution. Both categorically expose
cross-tenant data; this audit catches the schema-layer route in.

The check is cheap — Pydantic's model introspection makes
field-name lookups O(1) per model. We import every module under
`schemas/`, walk subclasses of BaseModel, and flag any whose
class name matches the input-schema pattern AND has an
`organization_id` field.

Allowlist surface for legitimate exceptions:

  * `_INPUT_SCHEMAS_WITH_ORG_ID` — input schemas that
    legitimately accept `organization_id` because the route
    handler IS cross-tenant by design. Today: empty. The list
    exists so the audit failure message can name the
    deliberate-exception path.

If you add an input schema with `organization_id`, add the
fully-qualified class name to that allowlist with a one-line
rationale. The PR review of the addition is where the
cross-tenant decision gets vetted.

This file is read-only — imports schemas + introspects fields.
Survives reverts.
"""

from __future__ import annotations

import importlib
import inspect
from pathlib import Path

from pydantic import BaseModel

# Suffix patterns identifying INPUT schemas. A schema with one of
# these suffixes is asserted NOT to have organization_id.
_INPUT_SCHEMA_SUFFIXES: tuple[str, ...] = (
    "Create",
    "Update",
    "Patch",
    "Input",
    "Payload",
    "Request",
    "In",  # e.g. NotificationPreferenceUpdate doesn't match but
    # bare `*In` schemas exist (rarely) — kept conservative.
)


# Suffix patterns identifying OUTPUT schemas. These are EXEMPT —
# response shapes legitimately include organization_id so the
# client can render "this row belongs to org X". A schema with
# one of these suffixes is NEVER flagged regardless of fields.
_OUTPUT_SCHEMA_SUFFIXES: tuple[str, ...] = (
    "Out",
    "Read",
    "Response",
    "Detail",
    "View",
    "Returned",
    "Created",  # e.g. WebhookSubscriptionCreated, InvitationCreated
    "Accepted",  # e.g. InvitationAccepted
    "Summary",
    "Row",
)


# Allowlist of `module.ClassName` strings for input schemas that
# legitimately include `organization_id`. Today empty — every
# input schema in schemas/ scopes the org via the AuthContext
# instead. New entries land in PR review with rationale.
_INPUT_SCHEMAS_WITH_ORG_ID: dict[str, str] = {
    # Format: "schemas.<module>.<ClassName>": "rationale"
    # Today: none.
}


def _is_input_schema_name(name: str) -> bool:
    """A class name suggests an INPUT schema iff it ends with one
    of the input suffixes AND doesn't end with an output suffix.
    `Created` is technically suffix-overlapping with `Create` but
    classified as output (it's the "we just created this, here's
    the payload" response). Output suffixes win on overlap.
    """
    # Output suffix wins (e.g. "InvitationCreated" is output).
    if any(name.endswith(suffix) for suffix in _OUTPUT_SCHEMA_SUFFIXES):
        return False
    return any(name.endswith(suffix) for suffix in _INPUT_SCHEMA_SUFFIXES)


def _schemas_dir() -> Path:
    return Path(__file__).parent.parent / "schemas"


def _walk_schema_classes():
    """Iterate every BaseModel subclass declared in `schemas/`.

    Returns tuples of `(module_name, class_name, model_class)`.
    Skips:
      * `__init__.py` (no schemas declared at package level)
      * Anything that fails to import (logged but not asserted —
        the test suite has separate import-smoke tests)
      * Classes that aren't direct or indirect BaseModel subclasses
    """
    schemas_root = _schemas_dir()
    for py_file in sorted(schemas_root.glob("*.py")):
        if py_file.name == "__init__.py":
            continue
        module_name = f"schemas.{py_file.stem}"
        try:
            module = importlib.import_module(module_name)
        except Exception:
            # Defensive — if a schema module fails to import, the
            # broader test suite catches it elsewhere. Don't double-
            # report here.
            continue
        for class_name, cls in inspect.getmembers(module, inspect.isclass):
            # Only schemas DECLARED in this module — not re-exports
            # of e.g. a base type from another module.
            if cls.__module__ != module_name:
                continue
            if not issubclass(cls, BaseModel):
                continue
            # Skip BaseModel itself and the abstract bases.
            if cls is BaseModel:
                continue
            yield module_name, class_name, cls


def test_no_input_schema_accepts_organization_id():
    """SECURITY-CRITICAL audit. For every Pydantic class in
    `schemas/` whose name matches the input-schema pattern,
    assert it has NO `organization_id` field.

    Failure surfaces a list of offending classes with their
    fully-qualified names + suggests the fix:

      1. If the field is a copy-paste mistake from an output
         schema, REMOVE it. The route handler reads
         `auth.organization_id` from the AuthContext.
      2. If the schema legitimately operates cross-tenant
         (rare), add the FQN to `_INPUT_SCHEMAS_WITH_ORG_ID`
         with a rationale.

    A regression here is the "partner mints resources against
    another tenant" failure mode — silent on success, only
    visible when a customer notices unexpected data.
    """
    offenders: list[str] = []
    for module_name, class_name, cls in _walk_schema_classes():
        if not _is_input_schema_name(class_name):
            continue
        if "organization_id" not in cls.model_fields:
            continue
        fqn = f"{module_name}.{class_name}"
        if fqn in _INPUT_SCHEMAS_WITH_ORG_ID:
            continue
        offenders.append(fqn)

    assert not offenders, (
        "These Pydantic input schemas accept `organization_id` "
        "from the client:\n  " + "\n  ".join(sorted(offenders)) + "\n\n"
        "SECURITY: an input schema with `organization_id` lets a "
        "client (partner / user) override the tenant attribution. "
        "The handler should read auth.organization_id from the "
        "AuthContext instead.\n\n"
        "If the field is a copy-paste mistake, REMOVE it. The "
        "route handler scopes via auth.organization_id.\n\n"
        "If the schema legitimately operates cross-tenant (rare), "
        "add the FQN to `_INPUT_SCHEMAS_WITH_ORG_ID` in this audit "
        "file with a rationale comment. PR review of THAT change "
        "is where the cross-tenant write decision gets vetted."
    )


def test_audit_actually_walks_input_schemas():
    """Sanity check: the audit's iteration logic finds at least
    a handful of input schemas. If a refactor renamed every
    *Create/*Update class to a different convention, the audit
    would silently pass with zero schemas scanned.

    Failing here means EITHER (a) the schema directory's naming
    convention changed (update `_INPUT_SCHEMA_SUFFIXES`) OR
    (b) the schemas dir got moved (update `_schemas_dir()`).
    """
    input_count = sum(1 for _module, name, _cls in _walk_schema_classes() if _is_input_schema_name(name))
    assert input_count >= 5, (
        f"Audit scanned {input_count} input schemas — implausibly "
        "few. The naming convention may have shifted (update "
        "`_INPUT_SCHEMA_SUFFIXES`) or the schemas/ dir moved "
        "(update `_schemas_dir()`)."
    )


def test_output_schema_classifier_correct():
    """Belt-and-suspenders: pin a few specific class names to
    verify the input-vs-output classifier behaves as documented.
    A regression in `_is_input_schema_name` would silently flip
    every schema's classification — either over-flagging output
    schemas (false alerts) or under-flagging input schemas
    (audit goes blind)."""
    # Output schemas — overlapping-suffix edge cases that should
    # be classified as output, not input.
    assert not _is_input_schema_name("InvitationCreated")  # `Created` wins over `Create`
    assert not _is_input_schema_name("WebhookSubscriptionCreated")
    assert not _is_input_schema_name("ProjectOut")
    assert not _is_input_schema_name("AuditEventDetail")
    assert not _is_input_schema_name("ScraperRunsSummaryRow")
    # Input schemas — should be flagged.
    assert _is_input_schema_name("ApiKeyCreate")
    assert _is_input_schema_name("ProjectUpdate")
    assert _is_input_schema_name("NotificationPreferenceUpdate")
    assert _is_input_schema_name("WebhookSubscriptionPatch")


def test_input_schemas_with_org_id_allowlist_is_minimal():
    """The carve-out for legitimate cross-tenant input schemas
    should stay small. Today: empty. Pin a low cap so a future
    addition is a deliberate decision, not a quiet creep."""
    assert len(_INPUT_SCHEMAS_WITH_ORG_ID) <= 1, (
        f"_INPUT_SCHEMAS_WITH_ORG_ID has "
        f"{len(_INPUT_SCHEMAS_WITH_ORG_ID)} entries: "
        f"{list(_INPUT_SCHEMAS_WITH_ORG_ID.keys())}. The allowlist "
        "exists for genuinely cross-tenant input schemas (rare); if "
        "it grows past 1 that's a signal cross-tenant writes are "
        "becoming a pattern — revisit the audit's posture."
    )
    for fqn, rationale in _INPUT_SCHEMAS_WITH_ORG_ID.items():
        assert rationale and rationale.strip(), (
            f"Allowlist entry `{fqn}` has empty rationale. PR reviewers need the WHY alongside the entry."
        )
