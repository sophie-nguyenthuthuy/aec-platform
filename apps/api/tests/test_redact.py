"""Email & phone PII redaction (cycle XX1).

Pinned seams:
  1. Replaces full match with placeholder.
  2. Idempotent.
  3. Multiple matches all redacted.
  4. None / empty → "".
  5. Pattern alignment with GG3 (email) + BB2 (phone).
"""

from __future__ import annotations

from services.redact import redact_email, redact_phone_vn, redact_pii

# ---------- Email ----------


def test_redact_email_simple():
    assert redact_email("Contact user@example.com today") == "Contact [email] today"


def test_redact_email_at_start():
    assert redact_email("user@example.com is the address") == "[email] is the address"


def test_redact_email_at_end():
    assert redact_email("write to user@example.com") == "write to [email]"


def test_redact_multiple_emails():
    assert redact_email("a@b.com and c@d.com") == "[email] and [email]"


def test_redact_email_with_subdomain():
    assert redact_email("admin@sub.example.com") == "[email]"


def test_redact_email_with_plus_tag():
    assert redact_email("user+tag@example.com") == "[email]"


def test_redact_email_no_match_passes_through():
    assert redact_email("no email here") == "no email here"


def test_redact_email_none():
    assert redact_email(None) == ""


def test_redact_email_empty():
    assert redact_email("") == ""


# ---------- Phone ----------


def test_redact_phone_simple():
    assert redact_phone_vn("Call 0901234567 now") == "Call [phone] now"


def test_redact_phone_with_country_code_plus():
    assert redact_phone_vn("Call +84901234567") == "Call [phone]"


def test_redact_phone_with_country_code_no_plus():
    assert redact_phone_vn("Call 84901234567") == "Call [phone]"


def test_redact_phone_with_spaces():
    assert redact_phone_vn("+84 90 123 4567") == "[phone]"


def test_redact_phone_with_hyphens():
    assert redact_phone_vn("0901-234-567") == "[phone]"


def test_redact_multiple_phones():
    text = "Call 0901234567 or 0987654321"
    redacted = redact_phone_vn(text)
    assert redacted.count("[phone]") == 2


def test_redact_phone_no_match():
    """Order #1234567890 — not a valid phone (doesn't start
    with valid prefix)."""
    assert redact_phone_vn("Order #1234567890") == "Order #1234567890"


def test_redact_phone_invalid_prefix():
    """0123456789 — `1` not a valid VN mobile prefix."""
    assert redact_phone_vn("0123456789") == "0123456789"


def test_redact_phone_none():
    assert redact_phone_vn(None) == ""


def test_redact_phone_empty():
    assert redact_phone_vn("") == ""


# ---------- redact_pii ----------


def test_redact_pii_both():
    text = "user@example.com phone 0901234567 contact"
    assert redact_pii(text) == "[email] phone [phone] contact"


def test_redact_pii_no_pii():
    assert redact_pii("plain text no pii") == "plain text no pii"


def test_redact_pii_none():
    assert redact_pii(None) == ""


# ---------- Idempotent ----------


def test_redact_email_idempotent():
    """Cardinal pin: re-running redaction yields same result.
    Pin so a refactor that produces output containing match-able
    patterns surfaces here."""
    cases = [
        "user@example.com",
        "Contact user@example.com today",
        "no email",
        "",
    ]
    for text in cases:
        once = redact_email(text)
        twice = redact_email(once)
        assert twice == once


def test_redact_phone_idempotent():
    cases = [
        "0901234567",
        "Call +84901234567 now",
        "no phone",
        "",
    ]
    for text in cases:
        once = redact_phone_vn(text)
        twice = redact_phone_vn(once)
        assert twice == once


def test_redact_pii_idempotent():
    cases = [
        "user@example.com phone 0901234567",
        "user@example.com",
        "0901234567",
        "no pii",
        "",
    ]
    for text in cases:
        once = redact_pii(text)
        twice = redact_pii(once)
        assert twice == once


# ---------- Placeholder safety ----------


def test_email_placeholder_no_at_sign():
    """Pin: `[email]` itself doesn't contain `@` so re-running
    won't re-redact and accumulate `[[email]]`."""
    placeholder = redact_email("user@example.com")
    assert placeholder == "[email]"
    assert "@" not in placeholder


def test_phone_placeholder_no_digits():
    """Pin: `[phone]` itself doesn't contain digits so re-running
    won't re-match and accumulate."""
    placeholder = redact_phone_vn("0901234567")
    assert placeholder == "[phone]"
    assert not any(c.isdigit() for c in placeholder)


# ---------- Pattern alignment ----------


def test_aligned_with_gg3_email():
    """Pin: redact pattern recognizes the same shape as GG3's
    `parse_email`. A canonically-formed valid email is redacted."""
    valid_emails = [
        "user@example.com",
        "user.name@example.com",
        "user+tag@example.com",
        "nguyen@vnpt.vn",
        "user@my-company.com",
    ]
    for email in valid_emails:
        text = f"contact {email} today"
        assert "[email]" in redact_email(text), f"failed to redact {email}"


def test_aligned_with_bb2_phone():
    """Pin: redact pattern recognizes the same shape as BB2's
    `parse_phone_vn`."""
    valid_phones = [
        "0901234567",
        "+84901234567",
        "84901234567",
        "0301234567",  # mobile prefix 3
        "0501234567",  # mobile prefix 5
        "0701234567",  # mobile prefix 7
        "0801234567",  # mobile prefix 8
    ]
    for phone in valid_phones:
        text = f"call {phone} please"
        assert "[phone]" in redact_phone_vn(text), f"failed to redact {phone}"
