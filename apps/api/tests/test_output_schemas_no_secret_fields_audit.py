"""Audit: Pydantic *output* schemas (Out / Detail / Response /
Read / Summary / Row / View / Returned) MUST NOT carry
secret-shaped fields.

Inverse of `test_input_schemas_no_organization_id_audit.py` —
that audit catches "client overrides tenant via body"; this one
catches "server leaks secrets via response."

The pattern this audit enforces:

  * **CREATE-response schemas** (`*Created`, `*Accepted`) MAY
    surface a secret on the one-shot create path. That's the
    documented contract: the customer sees the secret EXACTLY
    ONCE, on the response to their POST. Examples:
      - `WebhookSubscriptionCreated.secret` (HMAC signing secret)
      - `WebhookSubscriptionCreated` is also the rotate-secret
        response shape for the same reason

  * **LIST/DETAIL output schemas** (`*Out`, `*Read`, `*Response`,
    `*Detail`, `*Summary`, `*Row`, `*View`, `*Returned`) MUST
    NOT carry secret-shaped fields. A regression that added
    `secret` / `password` / `password_hash` / `private_key` to
    a list-row schema would leak every record's verification
    material on every GET — categorical secret exposure.

Why a separate audit from the per-router pin? The webhooks
router pin already catches `WebhookSubscriptionOut` regressing
to include `secret`. THIS audit catches the failure across
EVERY current and future schema in `schemas/`, regardless of
which router uses it. A new schema added to a different
vertical that copy-pastes a `secret: str` field would slip past
a per-router pin but get caught here.

Allowlist surface:

  * `_OUTPUT_SCHEMAS_WITH_SECRET` — output schemas that
    LEGITIMATELY surface a secret. Today: empty. Note that
    `*Created` schemas are exempted by suffix (they're the
    documented one-shot return path); only true `*Out` /
    `*Detail` / etc. that need a secret would land here.

This file is read-only — imports schemas + introspects fields.
Survives reverts.
"""

from __future__ import annotations

import importlib
import inspect
from pathlib import Path

from pydantic import BaseModel

# Field names treated as secret material. Each name is one whose
# presence in an output schema is categorically a regression:
#
#   * `secret` — webhook HMAC signing key, OAuth client secret
#   * `password` — never returned
#   * `password_hash` — bcrypt/argon2 hash; offline-brute-force
#     vector if leaked
#   * `private_key` — asymmetric crypto private half
#
# Deliberately NOT in the list:
#   * `token` — invitation tokens / SSE tickets ARE returned by
#     design; ambiguous classifier.
#   * `key` — `NotificationPreferenceOut.key` is the pref-key
#     name (e.g. "scraper_drift"), not a secret.
#   * `hash` — could be a content hash (file integrity) or a
#     password hash; ambiguous.
#
# Conservative surface keeps the audit's signal sharp.
_SECRET_FIELD_NAMES: frozenset[str] = frozenset(
    {
        "secret",
        "password",
        "password_hash",
        "private_key",
    }
)


# Suffix patterns identifying schemas this audit checks. Only
# LIST/DETAIL output suffixes — *Created / *Accepted are exempt
# because their documented role IS to surface the one-shot secret.
_GUARDED_OUTPUT_SUFFIXES: tuple[str, ...] = (
    "Out",
    "Read",
    "Response",
    "Detail",
    "Summary",
    "Row",
    "View",
    "Returned",
)


# Suffixes that EXEMPT a schema from this audit. *Created /
# *Accepted are the create-response shapes that legitimately
# carry a secret on the one-shot-return path. Anything in input
# schemas (Create/Update/etc.) is also exempt — different audit's
# domain.
_EXEMPT_SUFFIXES: tuple[str, ...] = (
    "Created",
    "Accepted",
    "Create",
    "Update",
    "Patch",
    "Input",
    "Payload",
    "Request",
)


# Allowlist of `module.ClassName` strings for output schemas that
# legitimately surface a secret. Today: empty. New entries land
# in PR review with rationale comments.
_OUTPUT_SCHEMAS_WITH_SECRET: dict[str, str] = {
    # Format: "schemas.<module>.<ClassName>": "rationale"
    # Today: none. *Created shapes (the documented one-shot path)
    # are exempted by suffix, not allowlist.
}


def _is_guarded_output_schema(name: str) -> bool:
    """A class name is in this audit's domain iff it ends with a
    guarded output suffix AND doesn't end with an exempt suffix.
    Exempt suffixes win on overlap (e.g. `WebhookSubscriptionCreated`
    matches `Created` first, exempt)."""
    if any(name.endswith(suffix) for suffix in _EXEMPT_SUFFIXES):
        return False
    return any(name.endswith(suffix) for suffix in _GUARDED_OUTPUT_SUFFIXES)


def _schemas_dir() -> Path:
    return Path(__file__).parent.parent / "schemas"


def _walk_schema_classes():
    """Iterate every BaseModel subclass declared in `schemas/`.
    Mirrors the helper in `test_input_schemas_no_organization_id_audit.py`
    — same pattern, intentionally duplicated so each audit file
    is independently reasonable to read.
    """
    schemas_root = _schemas_dir()
    for py_file in sorted(schemas_root.glob("*.py")):
        if py_file.name == "__init__.py":
            continue
        module_name = f"schemas.{py_file.stem}"
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue
        for class_name, cls in inspect.getmembers(module, inspect.isclass):
            if cls.__module__ != module_name:
                continue
            if not issubclass(cls, BaseModel):
                continue
            if cls is BaseModel:
                continue
            yield module_name, class_name, cls


def test_no_output_schema_carries_secret_field():
    """SECURITY-CRITICAL audit. For every Pydantic class in
    `schemas/` whose name matches a LIST/DETAIL output suffix,
    assert it has NO field in `_SECRET_FIELD_NAMES`.

    Failure surfaces the offending `(class, field)` pairs with
    their fully-qualified names. Resolution paths:

      1. **Field is a copy-paste mistake** — REMOVE it from the
         output schema. The verification material lives in the
         DB hash column; lists don't need it.

      2. **Output schema legitimately needs the secret** (rare —
         today never) — add the FQN to
         `_OUTPUT_SCHEMAS_WITH_SECRET` with a one-line rationale.
         The PR reviewer sees the rationale and decides whether
         to merge.

      3. **Field name is benign in this context** (e.g. `secret`
         on a non-credential model) — rename the field to
         disambiguate. Audit is intentionally over-strict on
         field names because the cost of a false alert is one
         rename PR; the cost of a missed leak is every customer's
         secret exposed.

    A regression here is THE secret-leak failure mode: every
    GET against the affected resource leaks every record's
    verification material to whoever can list.
    """
    offenders: list[str] = []
    for module_name, class_name, cls in _walk_schema_classes():
        if not _is_guarded_output_schema(class_name):
            continue
        for field_name in _SECRET_FIELD_NAMES:
            if field_name not in cls.model_fields:
                continue
            fqn = f"{module_name}.{class_name}"
            if fqn in _OUTPUT_SCHEMAS_WITH_SECRET:
                continue
            offenders.append(f"{fqn}.{field_name}")

    assert not offenders, (
        "These Pydantic output schemas surface secret-shaped "
        "fields:\n  " + "\n  ".join(sorted(offenders)) + "\n\n"
        "SECURITY: every GET against the affected resource leaks "
        "the secret to whoever can read. Verification material "
        "(secret / password / password_hash / private_key) "
        "MUST NOT appear in list / detail / summary response "
        "shapes.\n\n"
        "Resolution:\n"
        "  1. If the field is a copy-paste mistake, REMOVE it.\n"
        "  2. If the secret is legitimately part of a one-shot "
        "create response, RENAME the schema to end in `*Created` "
        "or `*Accepted` (those suffixes are exempt by design).\n"
        "  3. If the output truly needs the secret (rare), add "
        "the FQN to `_OUTPUT_SCHEMAS_WITH_SECRET` in this audit "
        "file with a rationale. PR review of that addition is "
        "where the leak-tradeoff gets vetted."
    )


def test_audit_actually_walks_output_schemas():
    """Sanity floor — the audit's iteration finds at least a
    handful of guarded output schemas. If a refactor renamed
    every `*Out` class to a different convention, the audit
    would silently pass with zero schemas scanned."""
    output_count = sum(1 for _module, name, _cls in _walk_schema_classes() if _is_guarded_output_schema(name))
    assert output_count >= 5, (
        f"Audit scanned {output_count} guarded output schemas — "
        "implausibly few. Either the naming convention shifted "
        "(update `_GUARDED_OUTPUT_SUFFIXES`) or the schemas/ dir "
        "moved (update `_schemas_dir()`)."
    )


def test_classifier_exempts_create_response_shapes():
    """Pin specific create-response class names to verify the
    suffix classifier exempts them. A regression that classified
    `WebhookSubscriptionCreated` as a guarded output would
    ALWAYS-fail the secret check (the schema legitimately has
    `secret: str`).

    Equally important: verify the classifier DOES catch
    `WebhookSubscriptionOut`-style names (so an actual leak via
    the list shape gets flagged).
    """
    # Exempt — *Created / *Accepted / input shapes.
    assert not _is_guarded_output_schema("WebhookSubscriptionCreated")
    assert not _is_guarded_output_schema("InvitationCreated")
    assert not _is_guarded_output_schema("InvitationAccepted")
    assert not _is_guarded_output_schema("ApiKeyCreate")
    assert not _is_guarded_output_schema("ProjectUpdate")

    # Guarded — these MUST be in the audit's domain.
    assert _is_guarded_output_schema("WebhookSubscriptionOut")
    assert _is_guarded_output_schema("ApiKeyDetail")
    assert _is_guarded_output_schema("AuditEventOut")
    assert _is_guarded_output_schema("ScraperRunsSummaryRow")


def test_secret_field_name_set_is_conservative():
    """Pin the secret-field-name set. Adding to the set tightens
    the audit (more flagged); removing weakens it (false-negatives
    appear). Either is a deliberate change — pin so it lands in
    PR review."""
    expected = {"secret", "password", "password_hash", "private_key"}
    assert frozenset(expected) == _SECRET_FIELD_NAMES, (
        f"_SECRET_FIELD_NAMES drifted: have {set(_SECRET_FIELD_NAMES)}, "
        f"want {expected}. Adding/removing names changes the audit's "
        "signal envelope; pin so the change is reviewed deliberately. "
        "If you broaden (e.g. adding `token`), be ready for the "
        "false-positive load on legitimate uses."
    )


def test_output_schemas_with_secret_allowlist_is_minimal():
    """The carve-out for legitimate secret-bearing list/detail
    schemas should stay empty. Pin a low cap so a future
    addition is a deliberate decision."""
    assert len(_OUTPUT_SCHEMAS_WITH_SECRET) <= 1, (
        f"_OUTPUT_SCHEMAS_WITH_SECRET has "
        f"{len(_OUTPUT_SCHEMAS_WITH_SECRET)} entries: "
        f"{list(_OUTPUT_SCHEMAS_WITH_SECRET.keys())}. Today should "
        "be 0; if you needed to add an entry, the rationale belongs "
        "in the comment alongside it."
    )
    for fqn, rationale in _OUTPUT_SCHEMAS_WITH_SECRET.items():
        assert rationale and rationale.strip(), f"Allowlist entry `{fqn}` has empty rationale."
