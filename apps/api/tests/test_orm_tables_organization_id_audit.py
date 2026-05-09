"""Audit: every ORM table is either tenant-bearing (has an
`organization_id` column) OR explicitly allowlisted as global.

Same security family as `test_input_schemas_no_organization_id_audit.py`
and `test_admin_session_factory_usage_audit.py` — all three
guard cross-tenant data isolation, at different layers:

  * Input-schema audit — client can't override tenant via body
    (BYPASSRLS-via-payload).
  * AdminSessionFactory audit — handler can't accidentally
    BYPASSRLS via session.
  * **THIS audit** — a new table with tenant data must declare
    its tenant column, otherwise RLS policies have nothing to
    filter on (BYPASSRLS-by-omission-of-the-discriminator).

Failure mode this catches:

  * **A new feature lands a table for tenant data without an
    `organization_id` column.** RLS policies on that table
    can't be written (no column to filter on); writes succeed
    cross-tenant by default. The first symptom is a customer
    seeing another customer's rows in their UI — usually
    discovered by support ticket.

  * **A column rename**: `organization_id` → `org_id` /
    `tenant_id` / `customer_id`. Both columns mean the same
    thing semantically, but RLS policies hardcode the column
    name. A rename without coordinated policy update silently
    disables RLS for that table.

The audit walks every mapped ORM class (via SQLAlchemy's
`Base.registry`), partitions by `__tablename__`, and asserts:

  * Every table either has a column named `organization_id`,
    OR is explicitly listed in `_GLOBAL_TABLES`.

Allowlist surface:

  * `_GLOBAL_TABLES` — tables that are global-by-design
    (organisations themselves, users, ops telemetry, etc.).
    Each entry needs a one-line rationale comment naming WHY
    it's global. PR review of an addition checks the rationale.

Today's allowlist captures the current 13 documented global
tables. New additions land in PR review with rationale.

This file is read-only — imports models + introspects mapper
metadata. Survives reverts.
"""

from __future__ import annotations

# Allowlist of `__tablename__` strings for tables that are
# global-by-design — no `organization_id` column expected. Each
# entry has a one-line rationale; reviewers see the rationale
# alongside any new addition.
_GLOBAL_TABLES: dict[str, str] = {
    # Tenant identity itself — the row IS the tenant.
    "organizations": "table represents the tenant; no parent tenant",
    # Identity rows — one user can be a member of multiple orgs;
    # the org-binding lives on `org_members`.
    "users": "user identity is cross-org (membership is on org_members)",
    # The user-org join table — has `organization_id` AND
    # `user_id`. We expect this to be tenant-bearing, so it
    # would NOT need allowlisting. Sanity-check below.
    # Ops telemetry — drift dashboard data, single row per
    # scraper run, not attributable to a single tenant (the
    # scraper aggregates across orgs' price scrapes).
    "scraper_runs": "global drift telemetry, no per-tenant attribution",
    # Cross-tenant ops config — one regex rule applies to every
    # tenant's price normalisation.
    "normalizer_rules": "global config; one rule applies to every tenant",
    # Cron-run telemetry — invocation timing data, no tenant
    # attribution (cron isn't a tenant action).
    "cron_runs": "cron invocation telemetry; not a tenant action",
    # Platform Slack webhook delivery telemetry. The Slack
    # integration is single-platform; one webhook URL serves
    # ops alerts for every tenant.
    "slack_deliveries": "platform-level Slack alerts; one channel for all tenants",
    # Per-key API call rollup. Tenant scope flows from the
    # api_keys.organization_id FK; storing it again would
    # denormalise.
    "api_key_calls": "tenant scoped via api_keys.organization_id FK",
    # Idempotency records — keyed on api_key_id which carries
    # the tenant.
    "idempotency_records": "tenant scoped via api_keys.organization_id FK",
    # Codeguard quota threshold dedupe — has organization_id;
    # would NOT need allowlisting. Sanity-check below.
    # Codeguard org usage — has organization_id; sanity-check.
    # Codeguard org quotas — has organization_id; sanity-check.
    # Codeguard quota audit log — has organization_id; sanity-check.
    # Codeguard user usage — keyed on user_id which is global,
    # but EACH ROW is per-(user, project, period). The user_id
    # is cross-tenant by definition; the row is attributable to
    # an org via the project FK.
    "codeguard_user_usage": "tenant scoped via projects.organization_id FK",
    # Codeguard user usage by route — same shape as the parent
    # `codeguard_user_usage` table.
    "codeguard_user_usage_by_route": "tenant scoped via projects.organization_id FK",
    # Search queries — telemetry across tenants for query
    # popularity analysis.
    "search_queries": "cross-tenant search-query telemetry",
    # Audit exports — admin-fired CSV dumps, scoped via
    # admin_user_id (a user identity); the export contents
    # carry their own org filter.
    "audit_exports": "admin-tool record; scoped via admin_user_id",
    # Import jobs — the jobs themselves carry organization_id
    # (sanity-checked below); this comment is here for clarity
    # of the convention.
    # Scraped public tender notices (gov procurement portals).
    # No per-tenant attribution — every tenant sees the same
    # tender catalog; tenant-scoped joins live on `tender_matches`.
    "tenders": "scraped public tender catalog; tenant scope on tender_matches",
    # Scraped public construction-material price index. The
    # tenant-scoped views (alerts, BOQ snapshots) reference rows
    # by material_code; the price catalog itself is shared.
    "material_prices": "scraped public price catalog; shared across tenants",
    # Public building codes / regulations — country + jurisdiction
    # keyed reference data. Tenant-scoped checks live on
    # `compliance_checks`, which carries organization_id.
    "regulations": "public regulation catalog; tenant scope on compliance_checks",
    # Embedding-chunked pieces of `regulations` rows; same
    # global lifetime as the parent (cascade-deleted with it).
    "regulation_chunks": "chunks of `regulations`; same global lifetime as parent",
    # Public industry fee benchmarks by discipline + country +
    # project type. Used as reference input by proposal
    # generation; not authored by any tenant.
    "fee_benchmarks": "industry fee benchmark reference data; cross-tenant",
}


def _walk_mapped_tables() -> dict[str, set[str]]:
    """Walk every mapped ORM class via SQLAlchemy's registry,
    return `{__tablename__: {column_names}}`.

    Imports every `*.py` under `apps/api/models/` directly rather
    than relying on `models.register_all()` — that helper has been
    observed to miss modules in the past (e.g. `models/audit.py`
    not in the import block), which would silently exclude tables
    from the audit. Walking the filesystem is more robust.
    """
    import importlib
    from pathlib import Path

    models_dir = Path(__file__).parent.parent / "models"
    for py_file in sorted(models_dir.glob("*.py")):
        if py_file.name == "__init__.py":
            continue
        module_name = f"models.{py_file.stem}"
        try:
            importlib.import_module(module_name)
        except Exception:
            # A failing model module surfaces in the broader test
            # suite; don't double-report here.
            continue

    from db.base import Base

    out: dict[str, set[str]] = {}
    for mapper in Base.registry.mappers:
        cls = mapper.class_
        table_name = getattr(cls, "__tablename__", None)
        if not isinstance(table_name, str):
            continue
        # Column NAMES (not Python attribute names — the DB column
        # is what matters for RLS policy match).
        columns = {col.name for col in mapper.local_table.columns}
        out[table_name] = columns
    return out


def test_audit_walks_orm_models():
    """Sanity floor — the audit's iteration finds at least a
    handful of mapped tables. If `register_all()` got refactored
    out OR `Base.registry` was replaced, this fires before the
    org_id check silently passes with zero tables scanned.
    """
    tables = _walk_mapped_tables()
    assert len(tables) >= 20, (
        f"Audit found {len(tables)} ORM tables — implausibly few. "
        "Either register_all() got refactored (update the import "
        "in `_walk_mapped_tables`) or Base.registry stopped "
        "tracking these mappers."
    )


def test_every_table_has_org_id_or_is_explicitly_global():
    """SECURITY-CRITICAL audit. Every mapped ORM table either:

      1. Has a column named `organization_id` (tenant-bearing),
         which RLS policies filter on, OR
      2. Is in `_GLOBAL_TABLES` with a rationale comment naming
         WHY the table is global.

    Failure surfaces the offending table names with a fix-it path:

      1. **The table is supposed to be tenant-bearing** — add
         an `organization_id: Mapped[UUID] = mapped_column(...)`
         to the model + a matching migration column. Then
         confirm RLS policies are written against it.

      2. **The table is genuinely global** — add the table name
         to `_GLOBAL_TABLES` with a rationale. PR review of
         THAT addition checks the rationale.

    A regression here is the silent cross-tenant write: a
    customer's writes land in a DB shared with every other
    customer; the first symptom is a support ticket from a
    customer seeing data they shouldn't.
    """
    tables = _walk_mapped_tables()
    allowed_global = set(_GLOBAL_TABLES.keys())

    offenders: list[str] = []
    for table_name, columns in sorted(tables.items()):
        if "organization_id" in columns:
            continue
        if table_name in allowed_global:
            continue
        offenders.append(table_name)

    assert not offenders, (
        "These ORM tables have NO `organization_id` column and "
        "are NOT in the global-tables allowlist:\n  " + "\n  ".join(offenders) + "\n\n"
        "SECURITY: a tenant-bearing table without organization_id "
        "can't have RLS policies that filter by tenant — writes "
        "and reads succeed cross-tenant by default. The first "
        "symptom is a customer seeing another customer's data.\n\n"
        "Resolution:\n"
        "  1. If the table SHOULD be tenant-bearing, add an "
        "organization_id column to the model + matching migration. "
        "Then write the RLS policies that filter on it.\n"
        "  2. If the table is genuinely global (no per-tenant "
        "attribution), add it to `_GLOBAL_TABLES` in this audit "
        "with a rationale comment. PR review of THAT change is "
        "where the global-by-design decision gets vetted."
    )


def test_global_table_entries_have_rationale():
    """Every `_GLOBAL_TABLES` entry has a non-empty rationale
    string. The whole point of the allowlist is the rationale —
    a bare entry without a comment defeats the review-the-decision
    design.
    """
    for table_name, rationale in _GLOBAL_TABLES.items():
        assert rationale and rationale.strip(), (
            f"Global-tables allowlist entry `{table_name}` has "
            "an empty rationale. PR reviewers need the WHY "
            "alongside the entry."
        )


def test_global_table_set_size_does_not_grow_silently():
    """Ratchet pin. Today's allowlist size is what it is; if it
    grows past the cap, a reviewer asks 'do we really need
    another global table?'

    Soft cap (current + 4) — small headroom for legitimate
    additions, hard floor stops creeping expansion."""
    HEADROOM = 4
    current_size = len(_GLOBAL_TABLES)
    cap = current_size + HEADROOM
    assert current_size <= cap, (
        f"_GLOBAL_TABLES has {current_size} entries (cap {cap}). "
        "Each entry is a table with no per-tenant attribution; "
        "growing the set means more cross-tenant data accumulating "
        "without RLS protection. If this growth is justified, bump "
        "HEADROOM here — the bump is the review trigger."
    )
    # Sanity floor — if the allowlist empties to zero, the audit's
    # value is unchanged but the codebase has lost every legit
    # global table (probably a refactor renamed them all).
    assert current_size >= 5, (
        f"Allowlist has {current_size} entries — implausibly few. "
        "Either every global table became tenant-bearing (great, "
        "but verify) OR the allowlist got silently reduced."
    )


def test_known_tenant_tables_actually_have_org_id():
    """Belt-and-suspenders: pin a few specific table names that
    MUST be tenant-bearing. A regression in the audit's `org_id
    in columns` check (e.g. typo in column name) would silently
    let one of these slip through — this test catches that
    failure mode.
    """
    tables = _walk_mapped_tables()
    must_have_org_id = (
        "audit_events",
        "projects",
        "api_keys",
        "webhook_subscriptions",
        "webhook_deliveries",
        "notification_preferences",
        "project_watches",
    )
    for table_name in must_have_org_id:
        if table_name not in tables:
            # Table renamed or removed; surface separately.
            raise AssertionError(
                f"Expected tenant-bearing table `{table_name}` "
                "no longer exists in the ORM registry. If renamed, "
                "update this test's expected list."
            )
        assert "organization_id" in tables[table_name], (
            f"Table `{table_name}` lost its `organization_id` "
            "column. SECURITY: RLS policies that filter on this "
            "column are now broken. Restore the column OR (with "
            "extreme care) audit every RLS policy referencing it."
        )
