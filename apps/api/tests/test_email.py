"""Email validation (cycle GG3, Python half).

Pinned seams (mirror of `apps/web/lib/__tests__/email.test.ts`):
  1. MAX_EMAIL_LENGTH = 254 (RFC 5321).
  2. MAX_LOCAL_PART_LENGTH = 64.
  3. Lowercased canonical (storage convention).
  4. Whitespace stripped on parse.
  5. Exactly one '@' separator.
  6. No leading/trailing dot in local or domain.
  7. No consecutive dots anywhere.
  8. TLD must be ≥2 chars.
  9. Domain labels: LDH (no leading/trailing hyphen).
 10. None / empty → None.
 11. Cross-language byte-for-byte parity with TS half.
"""

from __future__ import annotations

from services.email import (
    MAX_EMAIL_LENGTH,
    MAX_LOCAL_PART_LENGTH,
    email_domain,
    is_valid_email,
    parse_email,
)

# ---------- Constants ----------


def test_max_email_length_is_254():
    """RFC 5321 §4.5.3.1.3."""
    assert MAX_EMAIL_LENGTH == 254


def test_max_local_part_length_is_64():
    """RFC 5321 §4.5.3.1.1."""
    assert MAX_LOCAL_PART_LENGTH == 64


# ---------- Canonical valid ----------


def test_parses_simple_email():
    assert parse_email("user@example.com") == "user@example.com"


def test_parses_dotted_local_part():
    assert parse_email("user.name@example.com") == "user.name@example.com"


def test_parses_plus_tag():
    assert parse_email("user+tag@example.com") == "user+tag@example.com"


def test_parses_subdomain():
    assert parse_email("user@sub.example.com") == "user@sub.example.com"


def test_parses_vn_cctld():
    assert parse_email("nguyen@vnpt.vn") == "nguyen@vnpt.vn"


def test_parses_hyphen_in_domain():
    assert parse_email("user@my-company.com") == "user@my-company.com"


# ---------- Canonicalization ----------


def test_lowercases_local_and_domain():
    """Cardinal pin: storage convention is lowercased. A refactor
    that preserves user-typed case introduces a duplicate-row
    risk on the audit_row.actor_email unique index."""
    assert parse_email("USER@EXAMPLE.COM") == "user@example.com"


def test_strips_leading_trailing_whitespace():
    assert parse_email("  user@example.com  ") == "user@example.com"
    assert parse_email("\tuser@example.com\n") == "user@example.com"


def test_preserves_internal_special_chars_after_lowercase():
    assert parse_email("USER.NAME+TAG@example.com") == "user.name+tag@example.com"


# ---------- Structural rejection ----------


def test_rejects_missing_at_sign():
    assert parse_email("noatsign.com") is None


def test_rejects_multiple_at_signs():
    assert parse_email("a@b@c.com") is None


def test_rejects_empty_local_part():
    assert parse_email("@example.com") is None


def test_rejects_empty_domain():
    assert parse_email("user@") is None


# ---------- Local part rules ----------


def test_rejects_leading_dot_in_local():
    assert parse_email(".user@example.com") is None


def test_rejects_trailing_dot_in_local():
    assert parse_email("user.@example.com") is None


def test_rejects_consecutive_dots_in_local():
    assert parse_email("us..er@example.com") is None


def test_rejects_local_part_over_max():
    long_local = "a" * 65
    assert parse_email(f"{long_local}@example.com") is None


def test_accepts_local_part_at_max_boundary():
    local_at_64 = "a" * 64
    expected = f"{local_at_64}@example.com"
    assert parse_email(expected) == expected


# ---------- Domain rules ----------


def test_rejects_domain_without_tld():
    assert parse_email("user@example") is None


def test_rejects_leading_dot_in_domain():
    assert parse_email("user@.example.com") is None


def test_rejects_trailing_dot_in_domain():
    assert parse_email("user@example.com.") is None


def test_rejects_consecutive_dots_in_domain():
    assert parse_email("user@example..com") is None


def test_rejects_single_char_tld():
    """Pin: TLD must be ≥2 chars per RFC + ICANN policy."""
    assert parse_email("user@example.c") is None


def test_rejects_leading_hyphen_in_domain_label():
    assert parse_email("user@-example.com") is None


def test_rejects_trailing_hyphen_in_domain_label():
    assert parse_email("user@example-.com") is None


def test_accepts_hyphen_in_middle_of_label():
    assert parse_email("user@my-company.com") == "user@my-company.com"


# ---------- Total length ----------


def test_rejects_email_over_max_length():
    local = "a" * 60
    domain = "b" * 190 + ".com"
    email = f"{local}@{domain}"
    if len(email) > MAX_EMAIL_LENGTH:
        assert parse_email(email) is None


# ---------- Defensive ----------


def test_returns_none_for_none_and_empty():
    assert parse_email(None) is None
    assert parse_email("") is None
    assert parse_email("   ") is None


# ---------- is_valid_email ----------


def test_is_valid_email_for_valid():
    assert is_valid_email("user@example.com") is True


def test_is_valid_email_false_for_invalid():
    assert is_valid_email("invalid") is False
    assert is_valid_email(None) is False


# ---------- email_domain ----------


def test_email_domain_extracts():
    assert email_domain("user@example.com") == "example.com"


def test_email_domain_lowercases():
    assert email_domain("user@EXAMPLE.COM") == "example.com"


def test_email_domain_none_for_invalid():
    assert email_domain(None) is None
    assert email_domain("invalid") is None


# ---------- Cross-language consistency ----------


def test_matches_ts_half_byte_for_byte():
    """Cross-language pin: the Python and TS halves produce the
    same canonical (or None) for every input. A divergence (e.g.
    one half allowing single-char TLDs) would silently break
    parity between client-side validation and server-side."""
    cases = [
        ("user@example.com", "user@example.com"),
        ("USER@EXAMPLE.COM", "user@example.com"),
        ("user.name+tag@example.com", "user.name+tag@example.com"),
        ("nguyen@vnpt.vn", "nguyen@vnpt.vn"),
        ("user@my-company.com", "user@my-company.com"),
        ("  user@example.com  ", "user@example.com"),
        ("noatsign.com", None),
        ("a@b@c.com", None),
        ("@example.com", None),
        ("user@", None),
        (".user@example.com", None),
        ("user.@example.com", None),
        ("us..er@example.com", None),
        ("user@example", None),
        ("user@.example.com", None),
        ("user@example..com", None),
        ("user@example.c", None),
        ("user@-example.com", None),
        ("", None),
        ("   ", None),
    ]
    for input_text, expected in cases:
        assert parse_email(input_text) == expected, (
            f"parse_email({input_text!r}) = {parse_email(input_text)!r}, expected {expected!r}"
        )
