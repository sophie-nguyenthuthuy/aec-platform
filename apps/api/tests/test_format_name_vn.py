"""Vietnamese name formatter (cycle QQ2, Python half).

Pinned seams (mirror of `apps/web/lib/__tests__/format-name-vn.test.ts`):
  1. Default "full" → family first (VN convention).
  2. "western" → "given family", middle dropped.
  3. "initials" → all three parts.
  4. Empty family → "".
  5. Whitespace trimmed.
  6. Cross-language byte-for-byte parity.
"""

from __future__ import annotations

from services.format_name_vn import VietnameseName, format_name_vn

# ---------- Full format ----------


def test_full_default_vn_convention():
    """Cardinal pin: VN convention is family → middle → given."""
    name = VietnameseName(family="Nguyễn", middle="Văn", given="Anh")
    assert format_name_vn(name) == "Nguyễn Văn Anh"
    assert format_name_vn(name, "full") == "Nguyễn Văn Anh"


def test_full_empty_middle():
    name = VietnameseName(family="Trần", middle="", given="Linh")
    assert format_name_vn(name, "full") == "Trần Linh"


def test_full_empty_given():
    name = VietnameseName(family="Phạm", middle="Văn", given="")
    assert format_name_vn(name, "full") == "Phạm Văn"


def test_full_family_only():
    assert format_name_vn(VietnameseName("Lê", "", ""), "full") == "Lê"


def test_full_multiword_middle():
    name = VietnameseName(family="Phạm", middle="Thị Thu", given="Hương")
    assert format_name_vn(name, "full") == "Phạm Thị Thu Hương"


# ---------- Given format ----------


def test_given_returns_given_only():
    name = VietnameseName(family="Nguyễn", middle="Văn", given="Anh")
    assert format_name_vn(name, "given") == "Anh"


def test_given_empty_when_no_given():
    name = VietnameseName(family="Nguyễn", middle="Văn", given="")
    assert format_name_vn(name, "given") == ""


# ---------- Western format ----------


def test_western_reverses_given_family():
    """Cardinal pin: Western order is given-then-family."""
    name = VietnameseName(family="Nguyễn", middle="Văn", given="Anh")
    assert format_name_vn(name, "western") == "Anh Nguyễn"


def test_western_drops_middle():
    """Western convention often omits middle. Pin so a refactor
    that includes middle in western format surfaces here."""
    name = VietnameseName(family="Phạm", middle="Thị Thu", given="Hương")
    assert format_name_vn(name, "western") == "Hương Phạm"


def test_western_falls_back_to_family():
    name = VietnameseName(family="Lê", middle="", given="")
    assert format_name_vn(name, "western") == "Lê"


# ---------- Initials ----------


def test_initials_includes_all_three_parts():
    name = VietnameseName(family="Nguyễn", middle="Văn", given="Anh")
    assert format_name_vn(name, "initials") == "NVA"


def test_initials_multiword_middle():
    name = VietnameseName(family="Phạm", middle="Thị Thu", given="Hương")
    assert format_name_vn(name, "initials") == "PTTH"


def test_initials_omits_empty_middle():
    name = VietnameseName(family="Trần", middle="", given="Linh")
    assert format_name_vn(name, "initials") == "TL"


def test_initials_uppercased():
    """Pin: lowercase input still produces uppercase initials."""
    name = VietnameseName(family="nguyễn", middle="", given="anh")
    assert format_name_vn(name, "initials") == "NA"


# ---------- Whitespace ----------


def test_trims_segment_whitespace():
    name = VietnameseName(
        family="  Nguyễn  ",
        middle="  Văn  ",
        given="  Anh  ",
    )
    assert format_name_vn(name, "full") == "Nguyễn Văn Anh"


def test_whitespace_only_middle_treated_as_empty():
    name = VietnameseName(family="Trần", middle="   ", given="Linh")
    assert format_name_vn(name, "full") == "Trần Linh"


# ---------- Empty family ----------


def test_empty_family_returns_empty():
    """Cardinal pin: family REQUIRED. Empty family → empty output
    for ALL formats. Defends against "given-only" output that
    looks like a Western first name (e.g., audit attribution
    "approved by Anh" without "Nguyễn" is ambiguous in VN
    context — there are many Anhs)."""
    name = VietnameseName(family="", middle="Văn", given="Anh")
    assert format_name_vn(name, "full") == ""
    assert format_name_vn(name, "given") == ""
    assert format_name_vn(name, "western") == ""
    assert format_name_vn(name, "initials") == ""


def test_whitespace_only_family_treated_as_empty():
    name = VietnameseName(family="   ", middle="", given="Anh")
    assert format_name_vn(name, "full") == ""


# ---------- Frozen ----------


def test_vietnamese_name_is_frozen():
    name = VietnameseName(family="Nguyễn", middle="", given="")
    try:
        name.family = "Trần"  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("VietnameseName should be frozen")


# ---------- Cross-language consistency ----------


def test_matches_ts_half_byte_for_byte():
    """Cross-language pin: TS and Python halves format identically."""
    cases = [
        (VietnameseName("Nguyễn", "Văn", "Anh"), "full", "Nguyễn Văn Anh"),
        (VietnameseName("Nguyễn", "Văn", "Anh"), "given", "Anh"),
        (VietnameseName("Nguyễn", "Văn", "Anh"), "western", "Anh Nguyễn"),
        (VietnameseName("Nguyễn", "Văn", "Anh"), "initials", "NVA"),
        (VietnameseName("Phạm", "Thị Thu", "Hương"), "full", "Phạm Thị Thu Hương"),
        (VietnameseName("Phạm", "Thị Thu", "Hương"), "initials", "PTTH"),
        (VietnameseName("Lê", "", ""), "full", "Lê"),
        (VietnameseName("", "Văn", "Anh"), "full", ""),
    ]
    for name, fmt, expected in cases:
        assert format_name_vn(name, fmt) == expected, (
            f"format_name_vn({name!r}, {fmt!r}) = {format_name_vn(name, fmt)!r}, expected {expected!r}"
        )
