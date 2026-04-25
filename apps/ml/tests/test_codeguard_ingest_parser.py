"""Pure-logic tests for the codeguard ingest parser.

These pin two non-obvious behaviors that were added after the initial
naive heading-regex implementation blew up on real Vietnamese code text:

1. `_looks_like_heading` must reject body lines that accidentally match the
   numeric-prefix regex (e.g. "200 m², cho phép bố trí..." or "5000 m² phải
   được trang bị..."). These are sentences in prose, not section headings.
   Without this filter the parser shatters real sections at every numeric
   mid-sentence token.

2. `_CHUNK_MIN_CHARS` must be low enough (~50) to keep genuinely short
   subsections like QCVN 06:2022 §3.2.2 ("1,05 m đối với nhà chung cư cao
   tầng và 0,9 m đối với nhà ở riêng lẻ.", ~70 chars). A floor of 200 drops
   them silently.

If either of these regresses, end-to-end Q&A quality collapses because
half the corpus goes missing from the chunk store.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pipelines.codeguard_ingest import (
    _CHUNK_MIN_CHARS,
    _load_source_text,
    _looks_like_heading,
    chunk_section,
    split_into_sections,
)

FIXTURE = (
    Path(__file__).resolve().parent.parent / "fixtures" / "codeguard" / "qcvn_06_2022_excerpt.md"
)


# ---------- _looks_like_heading ----------


@pytest.mark.parametrize(
    "line",
    [
        "3.1 Số lượng lối thoát nạn",
        "3.2.1 Chiều rộng thông thủy của hành lang thoát nạn",
        "1.1 Phạm vi điều chỉnh",
        "Điều 12 Quy định chung",
        "5.2 Tạo áp buồng thang bộ",
    ],
)
def test_looks_like_heading_accepts_real_headings(line: str) -> None:
    assert _looks_like_heading(line) is True


@pytest.mark.parametrize(
    "line,why",
    [
        (
            "200 m², cho phép bố trí một lối thoát nạn.",
            "ends with period + contains comma (prose)",
        ),
        (
            "5000 m² phải được trang bị hệ thống báo cháy tự động địa chỉ, bao gồm đầu báo",
            "starts with unit 'm²' after number + contains comma",
        ),
        (
            "1,05 m đối với nhà chung cư cao tầng và 0,9 m đối với nhà ở riêng lẻ.",
            "comma-decimal numbers aren't section refs, regex wouldn't match anyway",
        ),
        (
            "20 Pa khi tất cả các cửa đóng, và không được vượt quá 50 Pa",
            "number followed by unit 'Pa' + mid-sentence comma",
        ),
    ],
)
def test_looks_like_heading_rejects_prose_with_leading_numbers(line: str, why: str) -> None:
    assert _looks_like_heading(line) is False, why


def test_looks_like_heading_rejects_overlong_line() -> None:
    # Over 220 chars — can't be a section header even if it starts with digits.
    line = "3.1 " + ("x " * 200)
    assert _looks_like_heading(line) is False


# ---------- chunk-size floor ----------


def test_chunk_min_chars_allows_short_subsections() -> None:
    """QCVN 06:2022 §3.2.2 body is ~70 chars. Floor above ~75 would drop it."""
    assert _CHUNK_MIN_CHARS <= 75, (
        f"_CHUNK_MIN_CHARS={_CHUNK_MIN_CHARS} is too high — §3.2.2 (body ~70 chars) "
        "and similar terse subsections will be silently dropped from the corpus."
    )


# ---------- End-to-end on the committed fixture ----------


def test_fixture_captures_every_expected_section() -> None:
    """Regression guard: the QCVN excerpt must yield all 13 expected section refs."""
    raw = _load_source_text(FIXTURE)
    sections = split_into_sections(raw)
    captured = {s.section_ref for s in sections}
    expected = {
        "1.1",
        "1.2",
        "2.1",
        "2.2",
        "3.1",
        "3.2.1",
        "3.2.2",
        "3.3",
        "4.1",
        "4.2",
        "4.3",
        "5.1",
        "5.2",
    }
    missing = expected - captured
    assert not missing, f"missing sections: {sorted(missing)}"


def test_fixture_sections_have_nonempty_titles_and_bodies() -> None:
    raw = _load_source_text(FIXTURE)
    sections = split_into_sections(raw)
    for s in sections:
        assert s.title.strip(), f"section {s.section_ref} has empty title"
        assert s.content.strip(), f"section {s.section_ref} has empty body"


def test_fixture_does_not_emit_false_positive_section_refs() -> None:
    """Body text starting with numbers ("200 m²...", "5000 m²...") must never
    appear as a section ref. This would indicate _looks_like_heading regressed."""
    raw = _load_source_text(FIXTURE)
    sections = split_into_sections(raw)
    refs = {s.section_ref for s in sections}
    # Every ref should match the "N[.N]*" shape, not raw body numbers.
    for ref in refs:
        parts = ref.split(".")
        assert all(p.isdigit() for p in parts), f"malformed section_ref: {ref!r}"
        # Top-level refs in this fixture are 1-5 (chapters). A ref like "200"
        # or "5000" would be a false positive from a body sentence.
        assert int(parts[0]) <= 10, f"suspicious top-level section ref: {ref!r}"


def test_chunk_section_preserves_short_sections_as_single_chunk() -> None:
    raw = _load_source_text(FIXTURE)
    sections = split_into_sections(raw)
    # Every fixture section is under _CHUNK_MAX_CHARS, so each produces exactly 1 chunk.
    for s in sections:
        chunks = chunk_section(s)
        assert len(chunks) == 1, (
            f"section {s.section_ref} ({len(s.content)} chars) produced "
            f"{len(chunks)} chunks — expected 1 for bodies under the max-chars threshold"
        )
        assert chunks[0].strip() == s.content.strip()
