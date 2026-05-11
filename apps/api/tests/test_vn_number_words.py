"""Vietnamese number-to-words for invoice receipts (cycle II3).

Pinned seams:
  1. 0 → "Không đồng".
  2. `mốt` rule: 21 → "Hai mươi mốt", 11 → "Mười một".
  3. `lăm` rule: 15 → "Mười lăm", 25 → "Hai mươi lăm",
     105 → "Một trăm linh năm" (lăm only after tens word).
  4. `linh` connector: 105 → "Một trăm linh năm".
  5. Long-form non-first trios: 1005 → "Một nghìn không trăm linh năm".
  6. Trailing "đồng" always.
  7. First letter capitalized.
  8. Negative → "Âm <words> đồng".
  9. None / NaN → "".
 10. Scales: nghìn/triệu/tỷ + composite "X nghìn tỷ".
"""

from __future__ import annotations

from services.vn_number_words import vnd_to_words

# ---------- Zero / boundary ----------


def test_zero_is_khong_dong():
    assert vnd_to_words(0) == "Không đồng"


def test_one_dong():
    assert vnd_to_words(1) == "Một đồng"


def test_nine_dong():
    assert vnd_to_words(9) == "Chín đồng"


# ---------- Tens ----------


def test_ten():
    assert vnd_to_words(10) == "Mười đồng"


def test_eleven_uses_mot_not_mot():
    """11 → "Mười một". Pin: `1` after `mười` (bare ten) stays as
    `một`. The `mốt` rule applies only after `X mươi` for X ≥ 2."""
    assert vnd_to_words(11) == "Mười một đồng"


def test_fifteen_uses_lam_not_nam():
    """15 → "Mười lăm". Pin: `5` after `mười` becomes `lăm`."""
    assert vnd_to_words(15) == "Mười lăm đồng"


def test_twenty():
    assert vnd_to_words(20) == "Hai mươi đồng"


def test_twenty_one_uses_mot():
    """21 → "Hai mươi mốt". Pin: `1` after `X mươi` (X ≥ 2)
    becomes `mốt`. NOT "hai mươi một"."""
    assert vnd_to_words(21) == "Hai mươi mốt đồng"


def test_twenty_five_uses_lam():
    """25 → "Hai mươi lăm". Pin: `5` after `mươi` becomes `lăm`."""
    assert vnd_to_words(25) == "Hai mươi lăm đồng"


def test_thirty_one_uses_mot():
    assert vnd_to_words(31) == "Ba mươi mốt đồng"


def test_ninety_nine():
    assert vnd_to_words(99) == "Chín mươi chín đồng"


# ---------- Hundreds ----------


def test_one_hundred():
    assert vnd_to_words(100) == "Một trăm đồng"


def test_one_hundred_one_uses_linh_one():
    """101 → "Một trăm linh một". Pin: `linh` connector when
    tens=0 and units > 0. Pin: `1` after `linh` stays `một`."""
    assert vnd_to_words(101) == "Một trăm linh một đồng"


def test_one_hundred_five_uses_linh_nam():
    """105 → "Một trăm linh năm". Pin: `5` after `linh` STAYS `năm`
    (NOT lăm). The `lăm` rule applies only after `mười`/`mươi`."""
    assert vnd_to_words(105) == "Một trăm linh năm đồng"


def test_one_hundred_eleven():
    """111 → "Một trăm mười một"."""
    assert vnd_to_words(111) == "Một trăm mười một đồng"


def test_one_hundred_fifteen_uses_lam():
    """115 → "Một trăm mười lăm". Pin: tens word present → lăm."""
    assert vnd_to_words(115) == "Một trăm mười lăm đồng"


def test_one_hundred_twenty_one_uses_mot():
    """121 → "Một trăm hai mươi mốt"."""
    assert vnd_to_words(121) == "Một trăm hai mươi mốt đồng"


def test_one_hundred_twenty_five_uses_lam():
    assert vnd_to_words(125) == "Một trăm hai mươi lăm đồng"


def test_one_hundred_ten():
    """110 → "Một trăm mười"."""
    assert vnd_to_words(110) == "Một trăm mười đồng"


def test_nine_hundred_ninety_nine():
    assert vnd_to_words(999) == "Chín trăm chín mươi chín đồng"


# ---------- Thousands ----------


def test_one_thousand():
    assert vnd_to_words(1000) == "Một nghìn đồng"


def test_one_thousand_with_long_form_filler():
    """1005 → "Một nghìn không trăm linh năm". Pin long-form
    invoice convention: non-first trios with hundreds=0 include
    the `không trăm` filler."""
    assert vnd_to_words(1005) == "Một nghìn không trăm linh năm đồng"


def test_one_thousand_fifty_long_form():
    """1050 → "Một nghìn không trăm năm mươi"."""
    assert vnd_to_words(1050) == "Một nghìn không trăm năm mươi đồng"


def test_one_thousand_five_hundred_no_filler():
    """1500 → "Một nghìn năm trăm". Hundreds non-zero → no filler."""
    assert vnd_to_words(1500) == "Một nghìn năm trăm đồng"


def test_one_thousand_two_hundred_thirty_four():
    assert vnd_to_words(1234) == "Một nghìn hai trăm ba mươi bốn đồng"


def test_thousand_filler_then_normal():
    """1234 ≠ 1004."""
    assert vnd_to_words(1234) == "Một nghìn hai trăm ba mươi bốn đồng"
    assert vnd_to_words(1004) == "Một nghìn không trăm linh bốn đồng"


# ---------- Millions ----------


def test_one_million():
    assert vnd_to_words(1_000_000) == "Một triệu đồng"


def test_one_million_two_hundred_thirty_four_thousand_five_hundred_sixty_seven():
    """The canonical mid-range invoice example."""
    assert vnd_to_words(1_234_567) == ("Một triệu hai trăm ba mươi bốn nghìn năm trăm sáu mươi bảy đồng")


def test_one_million_and_five():
    """1,000,005 — middle trios skipped, last trio gets `không trăm linh`."""
    assert vnd_to_words(1_000_005) == "Một triệu không trăm linh năm đồng"


def test_one_million_five_thousand():
    """1,005,000 — middle trio is 005, last trio is 000 (skipped)."""
    assert vnd_to_words(1_005_000) == "Một triệu không trăm linh năm nghìn đồng"


# ---------- Billions (tỷ) ----------


def test_one_billion():
    assert vnd_to_words(1_000_000_000) == "Một tỷ đồng"


def test_ten_billion():
    """10 tỷ. Pin so a refactor that conflates `tỷ` scale with
    `triệu` doesn't surface in production with a 1000x error."""
    assert vnd_to_words(10_000_000_000) == "Mười tỷ đồng"


def test_one_hundred_billion():
    assert vnd_to_words(100_000_000_000) == "Một trăm tỷ đồng"


def test_one_thousand_billion_uses_nghin_ty():
    """10^12 = nghìn tỷ. Pin the composite scale form."""
    assert vnd_to_words(1_000_000_000_000) == "Một nghìn tỷ đồng"


# ---------- Negative ----------


def test_negative_uses_am_prefix():
    """Refunds / corrections use negative amounts. Pin "Âm"
    capitalized as the leading word."""
    assert vnd_to_words(-1234) == "Âm một nghìn hai trăm ba mươi bốn đồng"


def test_negative_one():
    assert vnd_to_words(-1) == "Âm một đồng"


# ---------- Fractional / rounding ----------


def test_fractional_rounds_half_up():
    """JS-compatible half-up: 1234.5 → 1235."""
    assert vnd_to_words(1234.5) == "Một nghìn hai trăm ba mươi lăm đồng"


def test_fractional_rounds_down_below_half():
    assert vnd_to_words(1234.4) == "Một nghìn hai trăm ba mươi bốn đồng"


def test_zero_point_five_rounds_to_one():
    assert vnd_to_words(0.5) == "Một đồng"


def test_zero_point_four_rounds_to_zero():
    assert vnd_to_words(0.4) == "Không đồng"


# ---------- Defensive ----------


def test_none_returns_empty():
    """Chained-render-friendly: caller can do
    `vnd_to_words(invoice.amount)` without a None check."""
    assert vnd_to_words(None) == ""


def test_nan_inf_return_empty():
    assert vnd_to_words(float("nan")) == ""
    assert vnd_to_words(float("inf")) == ""
    assert vnd_to_words(float("-inf")) == ""


# ---------- Capitalization + đồng suffix ----------


def test_first_letter_always_capitalized():
    """Pin: every output starts with capital. The function is
    used in invoice templates that expect sentence-case."""
    cases = [1, 21, 100, 1234, 1_000_000, -5]
    for amount in cases:
        result = vnd_to_words(amount)
        assert result[0].isupper(), f"vnd_to_words({amount}) = {result!r} not capitalized"


def test_dong_suffix_always_present():
    """Pin: every non-empty output ends with `đồng`. The legal
    invoice form requires the unit suffix."""
    cases = [0, 1, 100, 1_000_000, -1234]
    for amount in cases:
        result = vnd_to_words(amount)
        assert result.endswith(" đồng"), f"vnd_to_words({amount}) = {result!r} missing 'đồng' suffix"
