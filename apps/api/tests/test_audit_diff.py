"""Audit diff summarization (cycle X1, Python half).

Pinned seams:
  1. Empty diff → empty text, zero changes.
  2. Two-key cap honored; total_changes still counts beyond cap.
  3. ∅ for absent keys, "null" distinct from ∅.
  4. dict/list values JSON-stringified (no spaces — matches TS).
  5. NaN-equals-NaN semantics (mirrors TS `Object.is`).
"""

from __future__ import annotations

from services.audit_diff import (
    SUMMARY_KEY_CAP,
    format_value,
    summarize_diff,
)

# ---------- format_value ----------


def test_format_value_renders_absent_as_empty_set_glyph():
    """Absent vs None must render distinctly — the ∅ glyph is the
    "absent" signal."""
    from services.audit_diff import _ABSENT

    assert format_value(_ABSENT) == "∅"


def test_format_value_renders_none_as_literal_null():
    """A field that was explicitly set to null IS a value — render
    as "null" so reviewers see the explicit-null operator action."""
    assert format_value(None) == "null"


def test_format_value_json_stringifies_dicts_and_lists():
    """Nested diffs stay one-line via JSON."""
    assert format_value({"status": "approved", "count": 3}) == '{"status":"approved","count":3}'
    assert format_value([1, 2, 3]) == "[1,2,3]"


def test_format_value_handles_un_serialisable_objects():
    """Defensive: a value that can't be JSON'd falls back to
    "[object]" rather than raising."""

    class _NotJsonable:
        pass

    # The default=str fallback makes most things serializable, but
    # an exotic shape that raises on str() too can fall through.
    # Pin the safety net with a self-referencing list.
    bad: list[object] = []
    bad.append(bad)
    out = format_value(bad)
    # Either the json fallback or the [object] sentinel — both are
    # acceptable; the row must not crash.
    assert isinstance(out, str)


def test_format_value_renders_primitives_via_str():
    assert format_value("draft") == "draft"
    assert format_value(42) == "42"
    assert format_value(True) == "True"


# ---------- summarize_diff ----------


def test_summarize_diff_empty_when_dicts_match():
    out = summarize_diff({"role": "member"}, {"role": "member"})
    assert out.text == ""
    assert out.total_changes == 0


def test_summarize_diff_handles_none_inputs():
    """Defensive: a None for either side is empty-dict semantically.
    Audit rows where the diff was never populated shouldn't crash
    the renderer."""
    out = summarize_diff(None, {"role": "admin"})
    assert "role: ∅ → admin" in out.text


def test_summarize_diff_renders_single_key_change():
    out = summarize_diff({"role": "member"}, {"role": "admin"})
    assert out.text == "role: member → admin"
    assert out.total_changes == 1


def test_summarize_diff_caps_at_two_keys_but_counts_all():
    """3 changes — inline shows 2, total_changes reports 3 so the
    caller can render '+ 1 more'."""
    out = summarize_diff({"a": 1, "b": 2, "c": 3}, {"a": 10, "b": 20, "c": 30})
    parts = out.text.split(" · ")
    assert len(parts) == SUMMARY_KEY_CAP
    assert out.total_changes == 3


def test_summarize_diff_absent_before_renders_added():
    out = summarize_diff({}, {"role": "admin"})
    assert out.text == "role: ∅ → admin"
    assert out.total_changes == 1


def test_summarize_diff_absent_after_renders_removed():
    out = summarize_diff({"role": "admin"}, {})
    assert out.text == "role: admin → ∅"


def test_summarize_diff_treats_null_distinct_from_absent():
    """absent → null IS a change (governance-bearing)."""
    out = summarize_diff({}, {"role": None})
    assert out.text == "role: ∅ → null"
    assert out.total_changes == 1


def test_summarize_diff_nan_equals_nan():
    """Mirrors TS `Object.is(NaN, NaN) === true`. A field that's
    NaN on both sides (impossible in practice but defensive) does
    NOT spam a fake change."""
    out = summarize_diff({"x": float("nan")}, {"x": float("nan")})
    assert out.total_changes == 0


def test_summarize_diff_nested_dict_change_renders_as_json():
    """A nested dict diff inlines as JSON. The summary doesn't
    drill into nested keys — that's what the row-expand button
    is for."""
    out = summarize_diff(
        {"address": {"city": "HCMC"}},
        {"address": {"city": "Hanoi"}},
    )
    # Both before + after rendered as JSON one-liners.
    assert "address: " in out.text
    assert '"HCMC"' in out.text
    assert '"Hanoi"' in out.text


def test_summary_key_cap_constant_pinned():
    """The cap matches `apps/web/lib/audit-diff.ts::SUMMARY_KEY_CAP`.
    A drift would mean the same audit row renders differently on
    Slack vs UI — confusing during incident retros."""
    assert SUMMARY_KEY_CAP == 2
