"""VN address formatter (cycle MM1, Python half).

Pinned seams (mirror of `apps/web/lib/__tests__/format-address-vn.test.ts`):
  1. VN_PROVINCES has 63 entries.
  2. Empty segments OMITTED.
  3. Whitespace-only treated as empty.
  4. is_valid_province case-sensitive + diacritic-sensitive.
  5. Cross-language byte-for-byte parity.
"""

from __future__ import annotations

from services.format_address_vn import (
    VN_PROVINCES,
    Address,
    format_address_vn,
    is_valid_province,
)

# ---------- VN_PROVINCES ----------


def test_provinces_has_63_entries():
    """5 centrally-administered cities + 58 provinces = 63."""
    assert len(VN_PROVINCES) == 63


def test_provinces_includes_5_central_cities():
    for city in ["Hà Nội", "Hồ Chí Minh", "Hải Phòng", "Đà Nẵng", "Cần Thơ"]:
        assert city in VN_PROVINCES


def test_provinces_includes_major_provinces():
    for prov in ["An Giang", "Bình Dương", "Đồng Nai", "Khánh Hòa", "Quảng Nam"]:
        assert prov in VN_PROVINCES


def test_provinces_excludes_invented_names():
    assert "Foobar" not in VN_PROVINCES
    assert "HCMC" not in VN_PROVINCES


def test_provinces_use_bare_canonical_names():
    """Pin: stored as bare name, NOT with "Tỉnh"/"Thành phố"
    prefix. A refactor that prefixes one half of the cross-
    language pair would surface here."""
    assert "Thành phố Hồ Chí Minh" not in VN_PROVINCES
    assert "Tỉnh An Giang" not in VN_PROVINCES


def test_provinces_is_frozen():
    assert isinstance(VN_PROVINCES, frozenset)


# ---------- format_address_vn ----------


def test_format_full_address():
    addr = Address(
        street="123 Lê Lợi",
        ward="Phường Bến Nghé",
        district="Quận 1",
        province="Hồ Chí Minh",
    )
    assert format_address_vn(addr) == "123 Lê Lợi, Phường Bến Nghé, Quận 1, Hồ Chí Minh"


def test_format_omits_empty_street():
    addr = Address(
        street="",
        ward="Phường Bến Nghé",
        district="Quận 1",
        province="Hồ Chí Minh",
    )
    assert format_address_vn(addr) == "Phường Bến Nghé, Quận 1, Hồ Chí Minh"


def test_format_omits_multiple_empty():
    addr = Address(street="", ward="", district="Quận 1", province="Hồ Chí Minh")
    assert format_address_vn(addr) == "Quận 1, Hồ Chí Minh"


def test_format_all_empty_returns_empty():
    addr = Address(street="", ward="", district="", province="")
    assert format_address_vn(addr) == ""


def test_format_province_only():
    addr = Address(street="", ward="", district="", province="Hà Nội")
    assert format_address_vn(addr) == "Hà Nội"


def test_format_treats_whitespace_only_as_empty():
    """Cardinal pin: no `"  ,  Hồ Chí Minh"` artifacts from
    whitespace-only segments."""
    addr = Address(
        street="   ",
        ward="\t",
        district="Quận 1",
        province="Hồ Chí Minh",
    )
    assert format_address_vn(addr) == "Quận 1, Hồ Chí Minh"


def test_format_trims_segments():
    addr = Address(
        street="  123 Lê Lợi  ",
        ward="",
        district="",
        province="  Hồ Chí Minh  ",
    )
    assert format_address_vn(addr) == "123 Lê Lợi, Hồ Chí Minh"


# ---------- is_valid_province ----------


def test_is_valid_known_provinces():
    assert is_valid_province("Hà Nội") is True
    assert is_valid_province("Hồ Chí Minh") is True
    assert is_valid_province("An Giang") is True


def test_is_valid_false_for_unknown():
    assert is_valid_province("Foobar") is False
    assert is_valid_province("HCMC") is False


def test_is_valid_strips_boundary_whitespace():
    assert is_valid_province("  Hà Nội  ") is True


def test_is_valid_case_sensitive():
    """Pin: case-sensitive. "ha noi" doesn't match "Hà Nội"."""
    assert is_valid_province("ha noi") is False
    assert is_valid_province("HÀ NỘI") is False


def test_is_valid_diacritic_sensitive():
    """Pin: "Ha Noi" (no diacritics) doesn't match. Canonical
    form requires exact diacritics — defends against silently
    accepting ambiguous user input."""
    assert is_valid_province("Ha Noi") is False


def test_is_valid_rejects_with_prefix():
    assert is_valid_province("Thành phố Hồ Chí Minh") is False
    assert is_valid_province("Tỉnh An Giang") is False


def test_is_valid_false_for_none_and_empty():
    assert is_valid_province(None) is False
    assert is_valid_province("") is False
    assert is_valid_province("   ") is False


# ---------- Address frozen ----------


def test_address_is_frozen():
    addr = Address(street="", ward="", district="", province="Hà Nội")
    try:
        addr.province = "Hồ Chí Minh"  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("Address should be frozen")


# ---------- Cross-language consistency ----------


def test_matches_ts_half_byte_for_byte():
    """Cross-language pin: TS and Python halves format identically."""
    cases = [
        (
            Address(
                street="123 Lê Lợi",
                ward="Phường Bến Nghé",
                district="Quận 1",
                province="Hồ Chí Minh",
            ),
            "123 Lê Lợi, Phường Bến Nghé, Quận 1, Hồ Chí Minh",
        ),
        (
            Address(street="", ward="", district="Quận 1", province="Hồ Chí Minh"),
            "Quận 1, Hồ Chí Minh",
        ),
        (Address(street="", ward="", district="", province="Hà Nội"), "Hà Nội"),
        (Address(street="", ward="", district="", province=""), ""),
    ]
    for addr, expected in cases:
        assert format_address_vn(addr) == expected, (
            f"format_address_vn({addr!r}) = {format_address_vn(addr)!r}, expected {expected!r}"
        )


def test_provinces_count_matches_ts_half():
    """The TS half pins 63 entries. Both halves must agree."""
    assert len(VN_PROVINCES) == 63
