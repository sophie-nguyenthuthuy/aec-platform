"""Multi-tenant ID prefix validator (cycle XX3).

Validate that resource IDs carry the expected org tenant prefix
to prevent cross-tenant ID leakage. Today every endpoint's
request-binding validator implements this check inline; the
audit row's resource_id parser duplicates the prefix extraction.
This module is the single source of truth.

  belongs_to_org(resource_id, org_id)    — bool
  extract_tenant_prefix(resource_id)     — slug or None

Resource ID format:
  `org_<slug>_<resource_type>_<unique>`

Examples:
  * `org_acme_user_42`
  * `org_acme_estimate_123`
  * `org_hung_vuong_corp_punchlist_99`  (multi-segment slug — see invariant)

Pinned invariants:
  * Both args required — empty / None either side → False
    (cross-tenant guard, defends against null-tenancy refactors).
  * Strict prefix match: `org_<exact_slug>_` must START the ID.
    `org_acmecorp_user_42` does NOT belong to org `acme` (pin
    against substring-prefix bug).
  * Case-sensitive (org slugs are lowercased canonical via CC3
    elsewhere).
  * `extract_tenant_prefix` returns the slug between `org_` and
    the FIRST `_` after — multi-segment slugs are NOT supported
    here (pin so `org_hung_vuong_*` extracts as `hung`, NOT
    `hung_vuong`; the canonical slug must be a single word).
  * `org_` prefix is REQUIRED (resource IDs without it return
    None / False — pin so legacy IDs without tenancy aren't
    silently accepted).

Pure stdlib.
"""

from __future__ import annotations


def belongs_to_org(
    resource_id: str | None,
    org_id: str | None,
) -> bool:
    """True iff `resource_id` is prefixed with `org_<org_id>_`.

    Strict prefix match — case-sensitive, exact slug.
    """
    if not resource_id or not org_id:
        return False
    expected_prefix = f"org_{org_id}_"
    return resource_id.startswith(expected_prefix)


def extract_tenant_prefix(resource_id: str | None) -> str | None:
    """Return the org slug prefix from a resource ID, or None.

    Format: `org_<slug>_<rest>` — slug is the first segment
    after `org_`. Single-word slugs only (matches CC3 canonical
    form: lowercased + non-alphanum collapsed to single hyphen,
    so an org slug never contains underscores).
    """
    if not resource_id:
        return None
    if not resource_id.startswith("org_"):
        return None
    rest = resource_id[len("org_") :]
    underscore_idx = rest.find("_")
    if underscore_idx <= 0:
        # Empty slug or no inner underscore → invalid.
        return None
    return rest[:underscore_idx]
