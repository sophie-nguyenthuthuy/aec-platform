"""Pin the field-shapes of `ProjectSummary`, `ProjectDetail`, `OrgOut`,
and `OrgMember`.

Why this exists: these four Pydantic models are the wire contract
for the busiest dashboard surfaces — the projects list, the
project-detail hub, the org switcher, and the members page. A drift
in any of them silently breaks rendering on the matching page.

Specific failure modes:

  * `ProjectSummary.open_tasks` dropped → projects-list page shows
    no "N tasks" badge per project; the hub looks empty.

  * `ProjectDetail.winwork` (or any of the 12 module rollups)
    dropped → that module's tab renders an empty card with no
    error. Frontend's `if (project.winwork) { ... }` reads
    `undefined`, skips render silently.

  * `OrgOut.role` dropped → org-switcher dropdown can't show "you
    are admin in Org X" badges; admin-only nav links disappear
    from non-admins' menus AND from admins' menus (the gate on
    `role === "admin"` reads `undefined`).

  * `OrgMember.email` dropped → member-management page shows
    blank rows. The `model_validate(...)` succeeds because email
    is optional in the schema's reverted state, then renders as
    empty string in the dashboard.

We don't pin the *nested rollup leaf shapes* (e.g. fields inside
`ProjectDetail.winwork`) — that would be 12 × 5+ fields of
fragile equality that change frequently as modules iterate. The
pin here is on the **set of top-level fields** + their
required-ness; the leaf shapes are the per-module schemas'
responsibility (and would be the right scope for a future
per-module pin file).
"""

from __future__ import annotations

from schemas.org import OrgMember
from schemas.orgs import OrgOut
from schemas.projects import ProjectDetail, ProjectSummary

# Each pin is `(field_set, required_set)` where `required_set ⊆
# field_set`. Comparing these as frozensets lets reorders pass —
# the JSON serialiser doesn't care about declaration order, and
# the frontend's destructuring is order-insensitive too. What
# matters is "the field exists" + "Pydantic enforces presence."


# ---------- ProjectSummary (projects list) ----------


PROJECT_SUMMARY_FIELDS: frozenset[str] = frozenset(
    {
        # Identity + tenancy
        "id",
        "organization_id",
        # Display
        "name",
        "type",  # commercial / residential / etc.
        "status",  # active / construction / closed / etc.
        # Specs
        "budget_vnd",
        "area_sqm",
        "address",
        "start_date",
        "end_date",
        "created_at",
        # Per-row badges (hot path: rendered on every list row)
        "open_tasks",
        "open_change_orders",
        "document_count",
    }
)


PROJECT_SUMMARY_REQUIRED: frozenset[str] = frozenset(
    {
        "id",
        "organization_id",
        "name",
        "status",
        "created_at",
        # `address` has a Pydantic default-factory dict (the inspect
        # showed `default=PydanticUndefined` but `is_required=False`),
        # so it's NOT in the required set even though it's not
        # nullable. Same for the badge counters which default to 0.
    }
)


# ---------- ProjectDetail (project hub) ----------


PROJECT_DETAIL_FIELDS: frozenset[str] = frozenset(
    {
        # Top-level identity / specs (mirrors ProjectSummary minus
        # the badge counters which are aggregated elsewhere on
        # this view).
        "id",
        "organization_id",
        "name",
        "type",
        "status",
        "budget_vnd",
        "area_sqm",
        "floors",
        "address",
        "start_date",
        "end_date",
        "metadata",
        "created_at",
        # The 12 module rollups. Each one feeds the corresponding
        # tab on the project hub. A drop here silently breaks the
        # tab — frontend renders an empty card with no error.
        "winwork",
        "costpulse",
        "pulse",
        "drawbridge",
        "handover",
        "siteeye",
        "codeguard",
        "schedulepilot",
        "submittals",
        "dailylog",
        "changeorder",
        "punchlist",
    }
)


PROJECT_DETAIL_REQUIRED: frozenset[str] = frozenset(
    {
        "id",
        "organization_id",
        "name",
        "status",
        "created_at",
    }
)


# ---------- OrgOut (org switcher) ----------


ORG_OUT_FIELDS: frozenset[str] = frozenset(
    {
        "id",
        "name",
        "slug",
        "plan",  # starter / pro / enterprise — controls feature gates
        "country_code",  # VN / US / etc. — drives locale defaults
        "created_at",
        # The caller's role IN this org. Drives admin-only nav
        # links across the dashboard. A drop silently shows the
        # admin menu to non-admins (server-side checks still gate
        # writes, but the menu surface is misleading).
        "role",
    }
)


ORG_OUT_REQUIRED: frozenset[str] = frozenset(
    {
        "id",
        "name",
        "slug",
        # `plan` is required (no default) because every paywall +
        # feature gate reads it; a None value would silently take
        # the "starter" branch on every gate. Required-with-no-
        # default forces the server to always set it.
        "plan",
        # `country_code` is required for similar reasons —
        # localisation defaults cascade off it (currency, address
        # format, time-zone). Optional would silently lower the
        # quality of every locale-defaulted view.
        "country_code",
        "role",
        "created_at",
    }
)


# ---------- OrgMember (members page) ----------


ORG_MEMBER_FIELDS: frozenset[str] = frozenset(
    {
        "membership_id",
        "user_id",
        "email",
        "full_name",
        "avatar_url",
        "role",  # owner / admin / member / viewer
        "joined_at",
    }
)


ORG_MEMBER_REQUIRED: frozenset[str] = frozenset(
    {
        "membership_id",
        "user_id",
        "email",
        "role",
        "joined_at",
    }
)


# ---------- Shared assertion helper ----------


def _assert_field_pin(
    model_cls,
    expected_fields: frozenset[str],
    expected_required: frozenset[str],
    name: str,
):
    """Assert the model's `model_fields` matches the pinned set +
    that required-ness lines up with the pinned subset."""
    actual_fields = frozenset(model_cls.model_fields.keys())
    actual_required = frozenset(n for n, f in model_cls.model_fields.items() if f.is_required())

    missing = expected_fields - actual_fields
    unexpected = actual_fields - expected_fields
    assert not missing, (
        f"{name} lost fields: {sorted(missing)}. If this is intentional, remove from the pinned set in the same PR."
    )
    assert not unexpected, (
        f"{name} gained fields the pin doesn't know about: {sorted(unexpected)}. "
        "Add to the pinned set + verify the frontend type mirrors it."
    )

    # Required-ness drift. Required→optional is the silent-bug
    # direction (model_validate accepts a payload missing the
    # field, downstream renderers crash).
    became_optional = expected_required - actual_required
    became_required = actual_required - expected_required
    assert not became_optional, (
        f"{name} fields became optional: {sorted(became_optional)}. "
        "This silently accepts payloads missing these fields — every "
        "downstream renderer that assumes presence will crash."
    )
    assert not became_required, (
        f"{name} fields became required: {sorted(became_required)}. Existing callers that don't supply them will 422."
    )


# ---------- Tests ----------


def test_project_summary_field_shape():
    _assert_field_pin(
        ProjectSummary,
        PROJECT_SUMMARY_FIELDS,
        PROJECT_SUMMARY_REQUIRED,
        "ProjectSummary",
    )


def test_project_detail_field_shape():
    _assert_field_pin(
        ProjectDetail,
        PROJECT_DETAIL_FIELDS,
        PROJECT_DETAIL_REQUIRED,
        "ProjectDetail",
    )


def test_project_detail_has_all_twelve_module_rollups():
    """Dedicated assertion for the module-tab contract. Each of the
    12 module-rollup fields drives one tab in the project hub. A
    drop here silently breaks that tab.

    Pin via name to make the failure message explicit (the field-
    set test above would also catch it, but the diff message there
    blends with top-level field changes — this one names the
    module that lost its rollup).
    """
    expected_modules = {
        "winwork",
        "costpulse",
        "pulse",
        "drawbridge",
        "handover",
        "siteeye",
        "codeguard",
        "schedulepilot",
        "submittals",
        "dailylog",
        "changeorder",
        "punchlist",
    }
    actual_modules = expected_modules & set(ProjectDetail.model_fields.keys())
    missing = expected_modules - actual_modules
    assert not missing, (
        f"ProjectDetail lost module rollup field(s): {sorted(missing)}. "
        f"The {sorted(missing)} tab(s) on the project hub will silently "
        "render empty (frontend's `if (project.<module>) {...}` reads "
        "undefined and skips)."
    )


def test_org_out_field_shape():
    _assert_field_pin(OrgOut, ORG_OUT_FIELDS, ORG_OUT_REQUIRED, "OrgOut")


def test_org_out_includes_role_field():
    """Dedicated assertion for `role` — the field that gates
    admin-only nav across the dashboard. A drop silently breaks
    role-based menu rendering (admin items either disappear from
    admins or appear for non-admins, depending on which way the
    `=== "admin"` check resolves on undefined)."""
    assert "role" in OrgOut.model_fields, (
        "OrgOut lost the `role` field. Admin-only nav links read "
        "`org.role === 'admin'` — undefined breaks both directions."
    )
    field = OrgOut.model_fields["role"]
    assert field.is_required(), (
        "OrgOut.role became optional. Frontend's role check reads "
        "`undefined` for missing values; admin nav silently disappears."
    )


def test_org_member_field_shape():
    _assert_field_pin(OrgMember, ORG_MEMBER_FIELDS, ORG_MEMBER_REQUIRED, "OrgMember")


def test_org_member_email_is_required():
    """The members page's primary identifier column. A drop or
    flip-to-optional silently shows blank rows — admins can't
    tell who's who."""
    field = OrgMember.model_fields["email"]
    assert field.is_required(), (
        "OrgMember.email became optional. The members page renders "
        "blank rows for missing emails; admins can't identify users."
    )
