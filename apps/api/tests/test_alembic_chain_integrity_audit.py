"""Audit: alembic migration chain integrity.

Migration chain corruption is silently broken until someone tries
to run migrations on a FRESH database (a new replica, a
post-incident restore, a contributor's local setup) and gets a
cryptic alembic error like:

  * "Multiple heads detected" — two migrations have no
    descendant; alembic can't pick one as `head`.
  * "Can't locate revision identified by 'X'" — a migration's
    `down_revision` points at a revision that doesn't exist.
  * Cycle in the chain — alembic walks `down_revision` forever.
  * Duplicate `revision = "X"` — two files claim the same id;
    alembic's behaviour is non-deterministic.

These failures are categorically different from "the migration is
wrong" — the migration logic might be perfect, but the chain
metadata is corrupt. The corruption happens silently during
merges (cherry-pick from a branch that introduced new migrations,
then the local branch's `down_revision` wires nothing).

This audit catches all four classes of corruption by AST-parsing
the `revision` / `down_revision` declarations from every file in
`alembic/versions/` and walking the graph. It runs in <0.1s and
doesn't import the migration modules or touch a real DB.

Allowlist surface (today populated with TODO-triage entries — the
audit caught real bugs on first authoring):

  * `_KNOWN_DANGLING_DOWN_REVISIONS` — revisions whose
    `down_revision` references a non-existent ancestor. Each is
    a real chain bug pending a senior-engineer fix.

  * `_KNOWN_MULTI_HEAD_REVISIONS` — heads that should be merged
    but aren't yet.

  * `_KNOWN_FILENAME_MISMATCHES` — files where the filename
    prefix doesn't match the `revision = "..."` declaration
    (renaming bug; mechanical fix).

The allowlist IS the triage list — fix each entry and remove it,
the audit ratchets down. The audit ships green WITH these
documented so the bug isn't lost.

This file is read-only. Survives reverts.
"""

from __future__ import annotations

import ast
from pathlib import Path

# Pre-merge heads that legitimately leave the chain with multiple
# unresolved tips. Each entry is a CHAIN BUG that the audit caught
# on its first run. They sit here as a triage list — a senior
# engineer should reconcile each one (the fix is to either repoint
# the dangling down_revision OR renumber the file) and remove the
# entry. DO NOT add new entries casually; every one is a fresh-DB
# deploy hazard.
_KNOWN_MULTI_HEAD_REVISIONS: frozenset[str] = frozenset(
    {
        # TODO(triage 2026-05): `0026_codeguard_quota_audit_log` references
        # an autogenerate-leftover `ceff072b3343` that doesn't exist.
        # Likely meant to descend from `0025_webhooks`. Until
        # reconciled, 0026 + descendants form a disconnected sub-
        # chain showing as additional heads. Remove this entry once
        # the orphan reference is fixed.
        "0026_codeguard_quota_audit_log",
        # TODO(triage 2026-05): `0025_notification_prefs` is a leaf with no
        # descendant. Likely needs a merge migration that lists it
        # alongside the other 0025_* head (`0025_webhooks`) as a
        # tuple `down_revision`. See `0006_merge_heads.py` (or any
        # other merge migration) for the pattern.
        "0025_notification_prefs",
        # TODO(triage 2026-05): same — `0025_webhooks` is a leaf because
        # its supposed descendant `0026` has the dangling
        # down_revision. Fixing 0026's down_revision to point here
        # would also remove this from the heads set.
        "0025_webhooks",
    }
)


# Allowlist for `down_revision` references that don't resolve to
# any known migration. Each entry is a CHAIN BUG that needs a real
# fix (pointing the down_revision at the correct ancestor). The
# audit ships green WITH these documented so the bug isn't lost —
# the allowlist IS the triage list.
_KNOWN_DANGLING_DOWN_REVISIONS: dict[str, str] = {
    # TODO(triage 2026-05): autogenerate left a hex revision id that was
    # never landed as a migration file. Fix: update the
    # `down_revision` line in `0026_codeguard_quota_audit_log.py`
    # to point at `0025_webhooks` (or whichever migration was
    # actually intended). Verify against the original PR.
    "0026_codeguard_quota_audit_log": (
        "down_revision points at autogenerate id 'ceff072b3343' that was never realised as a migration file"
    ),
}


# Allowlist for filename ↔ revision-id mismatches. Each entry is a
# renaming bug — typically the file was renamed but the
# `revision = "..."` line wasn't updated (or vice versa). The fix
# is mechanical: pick one (filename or revision) and align the
# other.
_KNOWN_FILENAME_MISMATCHES: frozenset[str] = frozenset(
    {
        # TODO(triage 2026-05): file says `_notifications`, revision says
        # `_thresholds`. The DB table the migration creates is
        # `codeguard_quota_threshold_notifications` — so the
        # FILENAME is right and the revision id should be renamed
        # to match.
        "0030_codeguard_quota_threshold_notifications.py",
        # TODO(triage 2026-05): file says `_by_route`, revision says
        # `_route`. Same shape — pick one and align.
        "0040_codeguard_user_usage_by_route.py",
    }
)


def _versions_dir() -> Path:
    """Path to `apps/api/alembic/versions/`."""
    return Path(__file__).parent.parent / "alembic" / "versions"


def _extract_revision_ids(py_path: Path) -> tuple[str | None, list[str]]:
    """Parse one migration file and return
    `(revision, down_revisions)`:
      * `revision` — the value of the `revision = "..."`
        module-level assignment, or None if missing.
      * `down_revisions` — list of revision ids the migration
        depends on. Length 1 for a linear chain, 2+ for merge
        migrations (`down_revision = ("a", "b")` form). Root
        migration has down_revision=None → empty list.

    AST-walks the module's top-level Assign nodes — robust to
    formatting / comments / ordering.
    """
    try:
        tree = ast.parse(py_path.read_text(), filename=str(py_path))
    except SyntaxError:
        return None, []

    revision: str | None = None
    down_revisions: list[str] = []

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        target_name = node.targets[0].id
        if target_name == "revision":
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                revision = node.value.value
        elif target_name == "down_revision":
            value = node.value
            if isinstance(value, ast.Constant):
                if value.value is None:
                    pass  # root migration; down_revisions stays []
                elif isinstance(value.value, str):
                    down_revisions = [value.value]
            elif isinstance(value, ast.Tuple | ast.List):
                for elt in value.elts:
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                        down_revisions.append(elt.value)

    return revision, down_revisions


def _build_chain():
    """Walk every migration file, parse, return a dict
    `{revision_id: (down_revisions, file_path)}`."""
    chain: dict[str, tuple[list[str], Path]] = {}
    for py_path in sorted(_versions_dir().glob("*.py")):
        if py_path.name == "__init__.py":
            continue
        revision, down_revisions = _extract_revision_ids(py_path)
        if revision is None:
            continue
        chain[revision] = (down_revisions, py_path)
    return chain


# ---------- Sanity floor ----------


def test_audit_finds_migration_files():
    """Sanity floor — the audit's iteration finds at least a
    handful of migrations. If alembic/versions/ moved or got
    wiped, this catches it before the chain assertions silently
    pass with zero migrations."""
    chain = _build_chain()
    assert len(chain) >= 5, (
        f"Audit found {len(chain)} migration files — implausibly "
        "few. Either alembic/versions/ moved (update _versions_dir) "
        "or migrations were wiped (broader regression worth surfacing)."
    )


# ---------- Revision uniqueness ----------


def test_revision_ids_are_unique():
    """Two migrations with the same `revision = "X"` is a
    structural corruption — alembic's behaviour on encountering
    duplicates is non-deterministic.

    Note: detection here is implicit (the `chain` dict can only
    hold one entry per revision id). We re-walk the files and
    count occurrences to surface the ACTUAL duplicate pair.
    """
    revision_to_files: dict[str, list[Path]] = {}
    for py_path in sorted(_versions_dir().glob("*.py")):
        if py_path.name == "__init__.py":
            continue
        revision, _ = _extract_revision_ids(py_path)
        if revision is None:
            continue
        revision_to_files.setdefault(revision, []).append(py_path)

    duplicates = {rev: [str(p.name) for p in files] for rev, files in revision_to_files.items() if len(files) > 1}
    assert not duplicates, (
        "These revision ids are claimed by multiple migration "
        f"files: {duplicates}. Alembic's behaviour on duplicates "
        "is non-deterministic; deploy outcome depends on OS file-"
        "iteration order. Pick one and renumber the other."
    )


# ---------- Down-revision integrity ----------


def test_down_revisions_resolve_to_known_revisions():
    """Every `down_revision` value (when not None) MUST match an
    existing revision in the chain. Dangling references make
    alembic abort with "Can't locate revision identified by 'X'"
    on fresh-DB migration runs.

    Allowlist `_KNOWN_DANGLING_DOWN_REVISIONS` skips entries
    documented as known bugs; each one is a TODO-triage item.
    """
    chain = _build_chain()
    known = set(chain.keys())

    dangling: list[str] = []
    for revision, (down_revisions, py_path) in chain.items():
        if revision in _KNOWN_DANGLING_DOWN_REVISIONS:
            continue
        for down in down_revisions:
            if down not in known:
                dangling.append(f"{py_path.name}: revision={revision!r} references unknown down_revision={down!r}")

    assert not dangling, (
        "These migrations reference down_revisions that don't "
        "exist:\n  " + "\n  ".join(sorted(dangling)) + "\n\n"
        "Alembic aborts on this with 'Can't locate revision "
        "identified by X' — usually discovered during fresh-DB "
        "setup. Either the down_revision is a typo (fix it) or "
        "the ancestor migration was renumbered without updating "
        "its descendants."
    )


# ---------- Roots ----------


def test_exactly_one_root_revision():
    """A linear (or branched) alembic chain has EXACTLY ONE root
    — the migration whose down_revision is None. Multiple roots
    means the chain has disconnected components; alembic's
    `upgrade head` would fail to pick a starting point."""
    chain = _build_chain()
    roots = [rev for rev, (down, _) in chain.items() if not down]
    assert len(roots) == 1, (
        f"Chain has {len(roots)} root migrations (down_revision=None): {sorted(roots)}. Want exactly 1."
    )


# ---------- Heads ----------


def test_at_most_one_head_revision_or_explicit_multi_head():
    """A migration is a HEAD iff no other migration's
    down_revision references it. After all merge migrations land,
    the chain has exactly ONE head — the latest deployable
    revision. Multiple unresolved heads means
    `alembic upgrade head` fails.

    Allowlist (`_KNOWN_MULTI_HEAD_REVISIONS`) lets deliberate
    pre-merge state through.
    """
    chain = _build_chain()
    referenced_as_down: set[str] = set()
    for _rev, (downs, _py) in chain.items():
        for down in downs:
            referenced_as_down.add(down)

    heads = {rev for rev in chain if rev not in referenced_as_down}
    unallowlisted_heads = heads - _KNOWN_MULTI_HEAD_REVISIONS

    assert len(unallowlisted_heads) <= 1, (
        f"Chain has {len(unallowlisted_heads)} unresolved heads "
        f"(would fail 'alembic upgrade head'): "
        f"{sorted(unallowlisted_heads)}\n\n"
        "Resolution:\n"
        "  1. Add a merge migration that lists ALL heads as its "
        "down_revision tuple. The merge resolves the branching.\n"
        "  2. If multiple heads are intentional (rare; pre-merge "
        "state), add the heads to `_KNOWN_MULTI_HEAD_REVISIONS` "
        "with a rationale comment."
    )


# ---------- Cycles ----------


def test_no_cycle_in_migration_chain():
    """Walking down_revision from any node MUST eventually reach
    the root (no cycles). A cycle makes alembic walk forever;
    `upgrade` and `downgrade` both hang.

    Detection: standard topological sort. If we can't toposort,
    there's a cycle.
    """
    chain = _build_chain()

    # Forward edges: rev → down_revisions.
    edges: dict[str, list[str]] = {rev: list(downs) for rev, (downs, _) in chain.items()}

    # In-degree against the down-edge: how many times this
    # revision is referenced by a descendant.
    in_degree: dict[str, int] = {rev: 0 for rev in chain}
    for _rev, downs in edges.items():
        for down in downs:
            if down in in_degree:
                in_degree[down] += 1

    # Start from heads (nothing references them as a parent). Walk down.
    queue = [rev for rev, deg in in_degree.items() if deg == 0]
    visited: set[str] = set()
    while queue:
        node = queue.pop()
        if node in visited:
            continue
        visited.add(node)
        for down in edges.get(node, []):
            if down not in in_degree:
                continue
            in_degree[down] -= 1
            if in_degree[down] == 0:
                queue.append(down)

    unvisited = set(chain.keys()) - visited
    assert not unvisited, (
        f"Migration chain has a cycle involving revisions: "
        f"{sorted(unvisited)}. Alembic walks down_revision forever "
        "on a cycle; both upgrade and downgrade hang."
    )


# ---------- Filename / revision id consistency ----------


def test_filename_prefix_matches_revision_id():
    """Convention: each migration file is named `<revision_id>.py`
    (or `<revision_id>_short_description.py`). A drift between
    filename and revision id is confusing AT BEST (filename leads
    ops to grep for the wrong id) and a structural bug AT WORST.

    Allowlist (`_KNOWN_FILENAME_MISMATCHES`) skips known renaming
    bugs pending mechanical fix.
    """
    chain = _build_chain()

    mismatches: list[str] = []
    for revision, (_downs, py_path) in chain.items():
        if py_path.name in _KNOWN_FILENAME_MISMATCHES:
            continue
        stem = py_path.stem
        if not stem.startswith(revision):
            mismatches.append(f"file={py_path.name!r}, revision={revision!r}")

    assert not mismatches, (
        "Migration filenames don't start with their revision id:\n  " + "\n  ".join(sorted(mismatches)) + "\n\n"
        "Convention: every migration file is named "
        "`<revision_id>.py` or `<revision_id>_<description>.py`. "
        "An ops engineer grepping for a revision id in the "
        "filenames would miss these — confusing during incident "
        "triage."
    )


# Alembic's `alembic_version` table pins `version_num` as
# `varchar(32)`. A revision id over that limit fails the chain step
# at runtime with `StringDataRightTruncation` — the migration's logic
# may be perfect, but `UPDATE alembic_version SET version_num='...'`
# truncates and Postgres rejects the write. The error surfaces only
# on actual upgrade against a real Postgres; pinning the limit here
# in CI catches it pre-merge.
#
# History: `0050_index_org_id_on_child_tables` (33) and
# `0051_retention_overrides_rls_with_check` (39) both shipped
# over-limit and red-gated CI on alembic upgrade. They were renamed
# to `0050_idx_...` (31) and `0051_retention_rls_with_check` (29).
_ALEMBIC_VERSION_NUM_MAX_LEN = 32


def test_revision_ids_fit_alembic_version_num_column():
    """Pin: every revision id is ≤32 chars (the
    `alembic_version.version_num` column width). The runtime error
    on overrun is `StringDataRightTruncation` from psycopg2 during
    the post-migration `UPDATE alembic_version` step — happens AFTER
    the migration's DDL has already partially run, so the chain
    state on disk and in the DB diverge.

    Easier to catch the over-long id in static CI than to
    triage the half-applied chain on a fresh DB.
    """
    chain = _build_chain()
    too_long = sorted(
        f"{revision!r} ({len(revision)} chars)" for revision in chain if len(revision) > _ALEMBIC_VERSION_NUM_MAX_LEN
    )
    assert not too_long, (
        f"These revision ids exceed alembic_version.version_num's "
        f"varchar({_ALEMBIC_VERSION_NUM_MAX_LEN}) column:\n  "
        + "\n  ".join(too_long)
        + "\n\nShorten the revision id (and rename the file to match — "
        "see `test_filename_prefix_matches_revision_id`). Sample fix: "
        "`0050_index_org_id_on_child_tables` (33) → "
        "`0050_idx_org_id_on_child_tables` (31)."
    )
