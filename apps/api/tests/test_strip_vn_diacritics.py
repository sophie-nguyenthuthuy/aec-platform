"""Vietnamese diacritic stripping for search (cycle BB3, Python half).

Pinned seams (mirror of `apps/web/lib/__tests__/strip-vn-diacritics.test.ts`):
  1. đ → d, Đ → D (NFD doesn't decompose these — explicit fold).
  2. All 6 tone marks on 'a' fold to 'a'.
  3. All vowel modifications fold to base vowel.
  4. Uppercase versions fold to uppercase ASCII.
  5. ASCII passes through unchanged.
  6. None / empty → "".
  7. Idempotent on repeat application.
  8. Output matches the TS half byte-for-byte (cross-language pin).
"""

from __future__ import annotations

from services.strip_vn_diacritics import strip_vn_diacritics


# ---------- Common cases ----------


def test_strips_diacritics_from_common_place_names():
    assert strip_vn_diacritics("Hà Nội") == "Ha Noi"
    assert strip_vn_diacritics("Đà Nẵng") == "Da Nang"
    assert strip_vn_diacritics("Sài Gòn") == "Sai Gon"
    assert strip_vn_diacritics("Huế") == "Hue"


def test_handles_full_personal_names():
    assert strip_vn_diacritics("Trần Hưng Đạo") == "Tran Hung Dao"
    assert strip_vn_diacritics("Nguyễn Văn Anh") == "Nguyen Van Anh"


# ---------- đ / Đ explicit fold ----------


def test_folds_lowercase_d_with_stroke():
    """Pin: NFD-only normalisation would leave đ untouched. The
    explicit fold is the critical Vietnamese-specific case — pin
    so a refactor that drops the explicit replace and relies only
    on `unicodedata.normalize` surfaces here."""
    assert strip_vn_diacritics("đường") == "duong"
    assert strip_vn_diacritics("đẹp") == "dep"


def test_folds_uppercase_d_with_stroke():
    assert strip_vn_diacritics("Đại học") == "Dai hoc"
    assert strip_vn_diacritics("ĐÔNG") == "DONG"


# ---------- Tone tables ----------


def test_folds_all_six_tones_on_a():
    """a (none), á (acute), à (grave), ả (hook), ã (tilde),
    ạ (dot below). All fold to plain 'a'."""
    assert strip_vn_diacritics("a á à ả ã ạ") == "a a a a a a"


def test_folds_all_six_modified_vowels():
    """The 6 modified-vowel base forms: ă â ê ô ơ ư."""
    assert strip_vn_diacritics("ă â ê ô ơ ư") == "a a e o o u"


def test_folds_full_o_table():
    """Every modified-tone combination of 'o' folds to 'o'.
    o ó ò ỏ õ ọ ô ố ồ ổ ỗ ộ ơ ớ ờ ở ỡ ợ — 17 forms total."""
    all_o = "ó ò ỏ õ ọ ô ố ồ ổ ỗ ộ ơ ớ ờ ở ỡ ợ"
    expected = "o " * 16 + "o"
    assert strip_vn_diacritics(all_o) == expected


def test_folds_full_e_table():
    """e é è ẻ ẽ ẹ ê ế ề ể ễ ệ — 12 forms."""
    all_e = "é è ẻ ẽ ẹ ê ế ề ể ễ ệ"
    expected = "e " * 10 + "e"
    assert strip_vn_diacritics(all_e) == expected


def test_folds_full_u_table():
    """u ú ù ủ ũ ụ ư ứ ừ ử ữ ự — 12 forms."""
    all_u = "ú ù ủ ũ ụ ư ứ ừ ử ữ ự"
    expected = "u " * 10 + "u"
    assert strip_vn_diacritics(all_u) == expected


def test_folds_full_i_table():
    """i í ì ỉ ĩ ị — 6 forms (no modified-i in Vietnamese)."""
    all_i = "í ì ỉ ĩ ị"
    expected = "i " * 4 + "i"
    assert strip_vn_diacritics(all_i) == expected


def test_folds_y_with_tones():
    """y ý ỳ ỷ ỹ ỵ — 6 forms."""
    all_y = "ý ỳ ỷ ỹ ỵ"
    expected = "y " * 4 + "y"
    assert strip_vn_diacritics(all_y) == expected


# ---------- ASCII passthrough ----------


def test_preserves_ascii_unchanged():
    assert strip_vn_diacritics("Plain ASCII") == "Plain ASCII"
    assert strip_vn_diacritics("hello world 123") == "hello world 123"
    assert strip_vn_diacritics("a-b_c.d") == "a-b_c.d"


def test_preserves_whitespace_and_punctuation():
    assert strip_vn_diacritics("Hà   Nội!") == "Ha   Noi!"
    assert strip_vn_diacritics("Một, hai, ba.") == "Mot, hai, ba."


# ---------- Defensive ----------


def test_returns_empty_for_none_and_empty():
    """Calling code can chain `strip_vn_diacritics(query)`
    without a None check before `.lower()`."""
    assert strip_vn_diacritics(None) == ""
    assert strip_vn_diacritics("") == ""


def test_idempotent():
    """Running twice yields the same result. Pin: a refactor
    that double-decomposes (e.g. somehow re-applies combining
    marks) would surface here."""
    once = strip_vn_diacritics("Trần Hưng Đạo")
    twice = strip_vn_diacritics(once)
    assert twice == once
    assert twice == "Tran Hung Dao"


# ---------- Cross-language consistency ----------


def test_search_use_case_canonical_match():
    """The audit search canonicalises both sides; pin that the
    canonical form of "Hà Nội" matches "Ha Noi" exactly."""
    title = strip_vn_diacritics("Hà Nội")
    query = strip_vn_diacritics("Ha Noi")
    assert title.lower() == query.lower()


def test_matches_ts_half_byte_for_byte():
    """Cross-language pin: the Python and TS halves must produce
    the same output for every input. A divergence (e.g. one half
    stripping ZWJ, the other not) would silently break search
    parity between the autocomplete (TS) and the API search (PG
    fallback Python)."""
    cases = [
        ("Hà Nội", "Ha Noi"),
        ("Đà Nẵng", "Da Nang"),
        ("Trần Hưng Đạo", "Tran Hung Dao"),
        ("đường", "duong"),
        ("ĐÔNG", "DONG"),
        ("Plain ASCII", "Plain ASCII"),
        ("", ""),
    ]
    for input_text, expected in cases:
        assert strip_vn_diacritics(input_text) == expected
