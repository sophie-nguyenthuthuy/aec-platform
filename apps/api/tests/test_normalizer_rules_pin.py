"""Pin the in-code material-coverage of `services.price_scrapers.normalizer._RULES`.

Why this exists: `_RULES` is the canonical list of regex rules that
map raw Vietnamese material descriptions to our `material_code`
catalogue. Each rule emits one specific code (e.g. `CONC_C30`,
`REBAR_CB500`). A revert that drops a rule has two compounding bad
effects:

  1. Every scrape after the revert pushes more rows into `unmatched`
     because the dropped rule's patterns no longer fire.
  2. `unmatched_ratio` rises → drift telemetry crosses 30% threshold
     → ops gets paged for a rule that was working yesterday → ops
     opens the admin UI to find no obvious cause (the regex looks
     fine, the patterns match by hand) → the actual cause (rule
     dropped from the in-code list) is invisible without diffing
     against this pin.

The patterns themselves are deliberately NOT pinned — DOC sites
rephrase materials over time and `_RULES` evolves with them. What's
pinned is the closed set of material_code values + the rule count.
A new rule (new material added to the catalogue) requires updating
this test in the same PR — that's the explicit signal that catalogue
coverage is being expanded.

DB-backed rules in `normalizer_rules` are intentionally NOT included
in this pin — those are ops-editable from the admin UI without a
deploy, and pinning them would defeat the editing workflow.
"""

from __future__ import annotations

from services.price_scrapers import normalizer

# Source of truth, pinned 2026-05-04. The exact set of codes the
# in-code rule list must emit. Each entry maps to one or more rules
# (multiple regexes can share a code, e.g. red brick has aliases) —
# but the SET of codes is what callers + telemetry consume.
EXPECTED_CODES: frozenset[str] = frozenset(
    {
        # Concrete (3 rules)
        "CONC_C25",
        "CONC_C30",
        "CONC_C40",
        # Rebar (2 rules)
        "REBAR_CB300",
        "REBAR_CB500",
        # Steel
        "STEEL_STRUCT",
        # Masonry (2 rules)
        "BRICK_AAC",
        "BRICK_RED",
        # Cement
        "CEMENT_PCB40",
        # Aggregates (2 rules)
        "SAND_FINE",
        "GRAVEL_1x2",
        # Finishes (5 rules)
        "TILE_CERAMIC",
        "PAINT_EXTERIOR",
        "PAINT_EMULSION",
        "PLASTER",
        "WATERPROOF_MEMBRANE",
    }
)


# Pinned rule count. Rule-count drift (multiple rules adding up to
# the same code, or splits/merges) often indicates a coverage
# regression even when the code-set stays stable.
EXPECTED_RULE_COUNT: int = 16


def test_normalizer_rules_emit_pinned_code_set():
    """Hard equality on the set of `material_code` values emitted by
    the in-code rule list. A drop here means a category of materials
    silently stopped being normalised — incoming scraper rows for
    that category go into `unmatched` and drift telemetry spikes."""
    actual_codes = frozenset(rule.code for rule in normalizer._RULES)
    missing = EXPECTED_CODES - actual_codes
    unexpected = actual_codes - EXPECTED_CODES
    assert not missing, (
        f"In-code rules no longer emit these material codes: {sorted(missing)}. "
        "If this is intentional (e.g. moved to DB-backed rules), remove from "
        "EXPECTED_CODES in the same PR. Without this update, every scrape "
        "post-revert will spike the unmatched ratio for the dropped category."
    )
    assert not unexpected, (
        f"In-code rules emit material codes the pin doesn't know about: "
        f"{sorted(unexpected)}. If this is intentional (new catalogue entry), "
        "add to EXPECTED_CODES + EXPECTED_RULE_COUNT in the same PR."
    )


def test_normalizer_rules_count_matches_expected():
    """Belt-and-suspenders for the count itself. Catches:

    * A duplicate rule (same code, different pattern) silently
      inflating coverage — the per-rule hit counts in
      `rule_hits_by_id` would split between the duplicates,
      making the admin UI's "fired N times" badges undercount.
    * A merge that drops one rule + folds its patterns into
      another. The code set above stays equal, but the rule
      count drops by one — this test catches that.
    """
    actual_count = len(normalizer._RULES)
    assert actual_count == EXPECTED_RULE_COUNT, (
        f"Normalizer has {actual_count} in-code rules; pin expects "
        f"{EXPECTED_RULE_COUNT}. Update both EXPECTED_RULE_COUNT and the "
        "matching EXPECTED_CODES entry in the same PR if intentional."
    )


def test_normalizer_rule_codes_are_uppercase_underscored():
    """Convention: codes are mostly UPPER_SNAKE_CASE matching the
    catalogue schema. The cost pipeline joins on `material_code`
    exactly, so a typo (whitespace, hyphens, accidentally lowercased
    word) silently fails to match catalogue rows.

    Exception: aggregate-size notation like `GRAVEL_1x2` keeps the
    lowercase `x` because that's the standard VN spec for "1cm-by-
    2cm crushed gravel" — flipping it to `1X2` would be inconsistent
    with the catalogue's source documents. We carve that out
    explicitly rather than relax the convention universally so a
    typo'd `BrickRed` still fails loudly.
    """
    for rule in normalizer._RULES:
        assert isinstance(rule.code, str), f"non-string code: {rule.code!r}"
        assert " " not in rule.code, f"normalizer rule code {rule.code!r} contains whitespace"
        assert "-" not in rule.code, f"normalizer rule code {rule.code!r} should use _ not -"
        # Strip the known "size-notation" lowercase letters before
        # the upper-case check. Catalogue convention is to write
        # 1x2 / 2x4 / etc. verbatim from the spec sheets.
        normalised = rule.code.replace("x", "X")
        assert normalised == normalised.upper(), (
            f"normalizer rule code {rule.code!r} has unexpected lowercase "
            "letters. Convention is UPPER_SNAKE_CASE; the only carve-out is "
            "size-notation `x` (e.g. `1x2`)."
        )


def test_normalizer_rule_canonical_names_are_non_empty():
    """`canonical` is the human-readable name shown in the admin UI
    + emitted in audit/digest emails. An empty string would render
    as a blank cell in the dashboard. Pin non-empty as a tripwire."""
    for rule in normalizer._RULES:
        assert rule.canonical, f"normalizer rule for code {rule.code!r} has empty canonical name"
        assert isinstance(rule.canonical, str)


def test_normalizer_rule_categories_match_known_set():
    """`category` is one of a small closed set used by the cost
    pipeline's bucketing. A rule with an off-set category (e.g. a
    typo `"masonary"` for `"masonry"`) would land in an unbucketed
    "other" group + miss the per-category cost rollups.

    Pin the closed set explicitly. New categories require a deliberate
    schema-vs-rule update on both the rule list AND the cost
    pipeline's bucketing logic.
    """
    KNOWN_CATEGORIES = {"concrete", "steel", "masonry", "finishing", "other"}
    for rule in normalizer._RULES:
        assert rule.category in KNOWN_CATEGORIES, (
            f"normalizer rule for code {rule.code!r} has category {rule.category!r} not in {KNOWN_CATEGORIES}"
        )
