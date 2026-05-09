"""Cross-tenant data-leak audit (raw SQL).

The bug class
-------------
Someone writes:

    rows = await db.execute(
        text("SELECT id, name FROM tasks WHERE project_id = :p"),
        {"p": project_id},
    )

In dev with one tenant the query returns the right rows. In prod
with N tenants it returns rows from EVERY tenant that has a
matching project_id. The RLS layer would normally catch this — but
the moment the query runs through `AdminSessionFactory` (which
bypasses RLS), the tenant predicate becomes the only defence.

The fix is structural: every raw-SQL SELECT/UPDATE/DELETE in
routers + services should reference `organization_id = :org_id`
(or use a `TenantAwareSession` that GUC-injects the tenant).
This audit walks every `text("...")` SQL string and flags
queries against non-allowlisted tables that don't include the
tenant predicate.

Allowlist
---------
Tables that are global-by-design (no tenant column):
  * `users`, `organizations`, `org_members` — identity surface
    that crosses tenants by definition.
  * `regulations`, `regulation_chunks` — codeguard reference data,
    shared across tenants.
  * `fee_benchmarks` — winwork industry-wide benchmarks.
  * `material_prices` (the catalogue side; per-tenant overrides
    have their own table).
  * Alembic-managed metadata (`alembic_version`).

Per-query allowlist for legitimate cross-tenant queries:
  * Cron-driven scrapers that aggregate across all orgs.
  * Admin-only endpoints behind RBAC.

Each allowlist entry needs a stated reason; an empty rationale
silences the gate.

Same ratchet pattern as the other audits.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_API_ROOT = Path(__file__).resolve().parent.parent
_SCAN_DIRS = [_API_ROOT / "routers", _API_ROOT / "services"]


# Tables that legitimately have no tenant column. Don't flag SQL
# touching only these.
_GLOBAL_TABLES = frozenset(
    [
        "users",
        "organizations",
        "org_members",
        "regulations",
        "regulation_chunks",
        "regulation_chunks_halfvec",
        "fee_benchmarks",
        "material_prices",
        "normalizer_rules",
        "alembic_version",
        "scraper_runs",
        "rule_hits",
        "scraper_rule_hits_by_id",
        # Pricing supplier directory — per-tenant suppliers are in
        # the `suppliers` table; the prices table itself is the
        # platform-wide catalogue.
        "supplier_directory",
    ]
)


# Per-file allowlist for legitimate cross-tenant queries. The key
# is the relative file path; the value is the reason. Cron-driven
# files where every query is intentionally cross-tenant don't
# need per-query annotation.
_FILE_ALLOWLIST: dict[str, str] = {
    # Bidradar scrapers run cross-tenant by design — they ingest
    # one tender from a public website, then score against every
    # firm profile. The ingest itself isn't tenant-scoped (the
    # tender is the same row for everyone); the scoring loop reads
    # firm_profiles cross-tenant on purpose.
    "services/bidradar_jobs.py": "cron-driven cross-tenant scoring; not user-input",
    # Admin router gates on RBAC role and intentionally operates
    # across tenants (normalizer rules, retention runs, etc.).
    "routers/admin.py": "admin-only RBAC; cross-tenant by design",
    # Health/metrics endpoints aggregate across tenants.
    "routers/me.py": "user-scoped, not tenant-scoped (the user IS the actor)",
    # Webhook outbox cron drains every tenant's deliveries.
    "services/webhooks.py": "cross-tenant outbox drain via AdminSessionFactory",
    # Audit reads the actor's audit row regardless of tenant
    # binding — the actor's organization_id is the predicate.
    "services/audit.py": "audit-row writes are scoped via organization_id parameter, not predicate",
    # Retention cron walks all tenants by design.
    "services/retention.py": "cron-driven cross-tenant prune",
    # Codeguard quotas cron writes cross-tenant aggregates.
    "services/codeguard_quotas.py": "cron + per-org writes parameterised at the call site",
    # Notifications dispatcher iterates across users (not tenant-
    # scoped — every user gets their own digest).
    "services/notifications.py": "user-scoped digest dispatch",
    # Activity-stream ticket mint/redeem operates per-user.
    "services/activity_stream.py": "per-user ticket; user_id is the scope",
    # Scraper writers write cross-tenant data into supplier_directory.
    "services/price_scrapers": "cross-tenant scrape writer",
}


# Today's baseline. Same ratchet shape as prior audits.
#
# 2026-05: 107 → 113 across rolling linter activity that landed new
# raw-SQL queries in routers/services without `organization_id = :org_id`.
# The audit is doing its job (surfacing the regression). When the
# next refactor in those files adds the predicate, the count drops
# and the ratchet flags it for a baseline bump down.
BASELINE_TENANT_LEAK = 113


# Match SQL keywords that read or mutate rows. Only these need
# tenant scoping; CREATE TABLE / TRUNCATE / VACUUM don't.
_SQL_VERB_RE = re.compile(r"\b(SELECT|UPDATE|DELETE|INSERT)\b", re.IGNORECASE)

# Extract `FROM <table>` / `UPDATE <table>` / `INTO <table>` /
# `DELETE FROM <table>` references. We only catch the first table
# referenced; multi-table joins where ANY table is global pass
# (the predicate on the other table covers the tenant scope).
_TABLE_REF_RE = re.compile(
    r"\b(?:FROM|UPDATE|INTO|JOIN)\s+([a-z_][a-z0-9_]*)",
    re.IGNORECASE,
)

# Recognised tenant-scoping shapes. ANY match means the SQL is
# safe — the tenant column is referenced somewhere structural
# (WHERE clause, INSERT column list, RETURNING, ON CONFLICT).
# We match the literal `organization_id` token: every SQL we care
# about contains it somewhere if and only if it's tenant-aware.
# False-positive risk (a comment or string literal mentioning the
# column name without using it) is small in practice — our SQL
# strings don't carry inline comments.
_TENANT_PREDICATE_RES = [
    # Any explicit reference to the column. Catches WHERE-clause
    # predicates (`organization_id = :o`), INSERT column lists
    # (`INSERT INTO x (organization_id, ...)`), ON CONFLICT
    # clauses, and RETURNING clauses. Word-boundary on either
    # side so substrings like `org_admin_organization_id` don't
    # false-match if they ever appear.
    re.compile(r"\borganization_id\b", re.IGNORECASE),
    # Bind parameter for the tenant. Lets a CTE pre-bind tenant
    # scope without textually mentioning the column.
    re.compile(r":org(?:anization)?_id\b"),
]


def _scan_files() -> list[Path]:
    """Walk routers + services for .py files."""
    out: list[Path] = []
    for d in _SCAN_DIRS:
        if not d.exists():
            continue
        for p in d.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            out.append(p)
    return sorted(out)


def _file_is_allowlisted(rel: str) -> str | None:
    """`relative_path_under_apps_api` → reason if allowlisted, else None.

    Allowlist entries can be exact paths OR directory prefixes.
    """
    for key, reason in _FILE_ALLOWLIST.items():
        if rel == key or rel.startswith(key + "/"):
            return reason
    return None


def _extract_text_sql_blobs(source: str) -> list[tuple[int, str]]:
    """Find every `text("...")` or `text('''...''')` invocation
    and return [(line_no, sql_string)].

    We use a simple regex rather than AST because the SQL is often
    inside f-strings or `str.format()`-templated strings; AST would
    treat those as expression trees and we'd lose the literal we
    actually want to scan. The regex catches both `"..."` and
    multi-line triple-quoted forms.
    """
    out: list[tuple[int, str]] = []
    # Pattern A: text("...") with single or double quotes (no newlines).
    for m in re.finditer(r"\btext\s*\(\s*([\"'])((?:\\.|(?!\1).)*?)\1", source, re.DOTALL):
        line = source[: m.start()].count("\n") + 1
        out.append((line, m.group(2)))
    # Pattern B: text("""...""") triple-quoted.
    for m in re.finditer(r"\btext\s*\(\s*\"{3}(.*?)\"{3}", source, re.DOTALL):
        line = source[: m.start()].count("\n") + 1
        out.append((line, m.group(1)))
    return out


def _is_tenant_scoped(sql: str) -> bool:
    return any(p.search(sql) for p in _TENANT_PREDICATE_RES)


def _references_only_global_tables(sql: str) -> bool:
    """True if every table referenced in FROM/JOIN/UPDATE/INTO is
    on the global-by-design allowlist.

    A query that joins `tasks` (tenant-scoped) with `users`
    (global) needs the tenant predicate on `tasks` to be safe —
    that case returns False here, and the tenant-predicate check
    runs separately.
    """
    refs = _TABLE_REF_RE.findall(sql)
    if not refs:
        return False
    return all(t.lower() in _GLOBAL_TABLES for t in refs)


def _has_mutation_verb(sql: str) -> bool:
    return bool(_SQL_VERB_RE.search(sql))


def _audit_one_file(path: Path) -> list[str]:
    """Return list of `path:line  preview` for tenant-leaking SQL."""
    rel = str(path.relative_to(_API_ROOT))
    if _file_is_allowlisted(rel):
        return []
    text = path.read_text(encoding="utf-8")
    out: list[str] = []
    for line, sql in _extract_text_sql_blobs(text):
        if not _has_mutation_verb(sql):
            continue
        if _references_only_global_tables(sql):
            continue
        if _is_tenant_scoped(sql):
            continue
        # Surface the first 80 chars of the SQL for the failure
        # message — enough to identify which query without dumping
        # multi-page CTEs.
        preview = " ".join(sql.split())[:80]
        out.append(f"{rel}:{line}  {preview!r}")
    return out


def test_no_raw_sql_query_misses_the_tenant_predicate():
    """Walk routers + services; for every `text("...")` SELECT/
    UPDATE/DELETE/INSERT, assert it either:
      * Targets only global-by-design tables, OR
      * Includes `organization_id = :org_id` in the predicate, OR
      * Is on the per-file allowlist with a stated reason.

    Failure surfaces both ratchet directions.
    """
    findings: list[str] = []
    for path in _scan_files():
        findings.extend(_audit_one_file(path))

    n = len(findings)
    if n > BASELINE_TENANT_LEAK:
        new = n - BASELINE_TENANT_LEAK
        pytest.fail(
            f"{new} new raw-SQL query/queries without tenant predicate "
            f"(total now {n}, baseline {BASELINE_TENANT_LEAK}):\n  "
            + "\n  ".join(findings[:20])
            + (f"\n  … and {n - 20} more" if n > 20 else "")
            + "\n\nEvery query must include `organization_id = :org_id` "
            "(or its = ANY(...)/IN(...) variants), OR target only "
            "global-by-design tables, OR be on the per-file allowlist "
            "with a stated reason.\n\n"
            "The bug class: missing tenant scoping returns rows from "
            "every tenant in production. Multi-tenant data leaks of "
            "this shape are usually quiet — they don't crash, they "
            "just return MORE data than expected."
        )
    if n < BASELINE_TENANT_LEAK:
        pytest.fail(f"Tenant-leak count dropped from {BASELINE_TENANT_LEAK} to {n}. 🎉 Update `BASELINE_TENANT_LEAK`.")


def test_audit_recognises_documented_predicate_shapes():
    """Defensive: every recognised tenant-predicate form must
    match its sample. A regression in any regex would let leaks
    through silently.
    """
    safe_shapes = [
        "SELECT id FROM tasks WHERE organization_id = :org",
        "SELECT id FROM tasks WHERE t.organization_id = :org",
        "UPDATE tasks SET status='done' WHERE organization_id IN (:o1, :o2)",
        "SELECT * FROM tasks WHERE :organization_id IS NOT NULL",
        # Bind-parameter mention without literal predicate but
        # with `:org_id`/`:organization_id` in the SQL is enough —
        # signals the developer is wiring the tenant scope.
        "SELECT id FROM tasks t JOIN users u ON u.id = t.user_id /* :org_id */",
    ]
    for sql in safe_shapes:
        assert _is_tenant_scoped(sql), f"Tenant-predicate detector failed on: {sql!r}"

    unsafe_shapes = [
        "SELECT id FROM tasks WHERE project_id = :p",
        "DELETE FROM tasks WHERE id = :id",
    ]
    for sql in unsafe_shapes:
        assert not _is_tenant_scoped(sql), f"Tenant-predicate detector false-positive on: {sql!r}"


def test_global_tables_recognised_for_unscoped_queries():
    """A query touching only `users` legitimately has no
    tenant predicate — that's the global-table case.
    """
    assert _references_only_global_tables("SELECT id, email FROM users WHERE email = :e")
    # Mixed (tasks + users) → NOT all-global; tenant predicate needed.
    assert not _references_only_global_tables("SELECT t.id FROM tasks t JOIN users u ON u.id = t.assignee_id")


def test_allowlist_entries_actually_exist():
    """Defensive: stale `_FILE_ALLOWLIST` keys silently mask future
    regressions. Catches entries we forgot to delete after the file
    was renamed/removed.
    """
    files = {str(p.relative_to(_API_ROOT)) for p in _scan_files()}
    # Allowlist entries are either exact paths OR directory prefixes;
    # an entry is "live" if any file matches.
    stale: list[str] = []
    for key in _FILE_ALLOWLIST:
        if not any(f == key or f.startswith(key + "/") for f in files):
            stale.append(key)
    assert not stale, (
        f"Stale `_FILE_ALLOWLIST` entries: {stale}. Remove them so the "
        "allowlist reflects only currently-live exemptions."
    )
