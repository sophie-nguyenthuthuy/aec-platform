"""Email domain allowlist validator (cycle YY3).

Pinned seams:
  1. Empty allowed_domains → True (no restriction).
  2. Invalid email → False.
  3. Case-insensitive domain comparison.
  4. EXACT match (no wildcard subdomain).
  5. Composes with GG3.
"""

from __future__ import annotations

from services.email import email_domain
from services.email_domain_allowlist import email_domain_allowed

# ---------- Allowed match ----------


def test_exact_domain_match():
    assert email_domain_allowed("user@example.com", {"example.com"}) is True


def test_match_in_multi_domain_set():
    assert (
        email_domain_allowed(
            "user@example.com",
            {"other.com", "example.com", "third.com"},
        )
        is True
    )


def test_vn_cctld_match():
    assert email_domain_allowed("nguyen@vnpt.vn", {"vnpt.vn"}) is True


# ---------- Disallowed ----------


def test_different_domain_rejected():
    assert email_domain_allowed("user@evil.com", {"example.com"}) is False


def test_subdomain_NOT_match_parent():
    """Cardinal pin: EXACT match. `user@mail.example.com` does
    NOT match allowed `example.com` (subdomains require
    explicit listing). Defends against silent subdomain
    matching that could let a compromised subdomain SMTP
    server claim parent-domain identity."""
    assert (
        email_domain_allowed(
            "user@mail.example.com",
            {"example.com"},
        )
        is False
    )


def test_parent_NOT_match_subdomain():
    """Symmetric: `user@example.com` doesn't match allowed
    `mail.example.com`."""
    assert (
        email_domain_allowed(
            "user@example.com",
            {"mail.example.com"},
        )
        is False
    )


# ---------- Case insensitivity ----------


def test_uppercase_email_matches():
    assert email_domain_allowed("user@EXAMPLE.COM", {"example.com"}) is True


def test_uppercase_allowed_matches():
    assert email_domain_allowed("user@example.com", {"EXAMPLE.COM"}) is True


def test_mixed_case():
    assert email_domain_allowed("user@Example.Com", {"example.com"}) is True


# ---------- Empty allowlist ----------


def test_empty_allowed_domains_true():
    """Cardinal pin: empty set = no restriction → all valid
    emails pass. Pin so unconfigured orgs accept any valid
    email rather than blocking everyone."""
    assert email_domain_allowed("user@example.com", set()) is True


def test_allowed_with_only_empty_strings_true():
    """Pin: a set with only empty/whitespace entries normalizes
    to empty (no restriction)."""
    assert email_domain_allowed("user@example.com", {"", "   "}) is True


def test_empty_with_invalid_email_false():
    """Even with no restriction, INVALID emails reject."""
    assert email_domain_allowed("invalid", set()) is False


# ---------- Invalid email ----------


def test_invalid_email_rejected():
    assert email_domain_allowed("not-an-email", {"example.com"}) is False
    assert email_domain_allowed("@example.com", {"example.com"}) is False
    assert email_domain_allowed("user@", {"example.com"}) is False


def test_none_email_rejected():
    assert email_domain_allowed(None, {"example.com"}) is False


def test_empty_email_rejected():
    assert email_domain_allowed("", {"example.com"}) is False


# ---------- Whitespace tolerance in allowlist ----------


def test_allowed_domain_with_whitespace_normalized():
    assert email_domain_allowed("user@example.com", {"  example.com  "}) is True


# ---------- Cross-cycle composition with GG3 ----------


def test_composes_with_gg3_email_domain():
    """Cardinal cross-cycle pin: this module's check is
    consistent with GG3's `email_domain` extraction."""
    # GG3 returns the lowercased domain.
    assert email_domain("USER@EXAMPLE.COM") == "example.com"

    # This module compares against the same canonical.
    assert (
        email_domain_allowed(
            "USER@EXAMPLE.COM",
            {"example.com"},
        )
        is True
    )


def test_gg3_invalid_email_propagates():
    """GG3 returning None for invalid email → this module rejects.
    Pin alignment so a refactor that loosens GG3 doesn't slip
    invalid emails past."""
    invalid_cases = [
        "not-an-email",
        "user@",
        "@example.com",
        ".user@example.com",
        "user@example",
    ]
    for email in invalid_cases:
        assert email_domain(email) is None
        assert email_domain_allowed(email, {"example.com"}) is False


# ---------- Realistic scenarios ----------


def test_org_invite_only_company_emails():
    """Realistic: Vingroup org allows only @vingroup.com.vn."""
    allowed = {"vingroup.com.vn"}
    assert email_domain_allowed("staff@vingroup.com.vn", allowed) is True
    assert email_domain_allowed("contractor@gmail.com", allowed) is False


def test_org_invite_multiple_allowed_domains():
    """Some orgs allow multiple sister-company domains."""
    allowed = {"vingroup.com.vn", "vinhomes.vn", "vinmec.com"}
    assert email_domain_allowed("ceo@vingroup.com.vn", allowed) is True
    assert email_domain_allowed("doctor@vinmec.com", allowed) is True
    assert email_domain_allowed("user@gmail.com", allowed) is False


def test_iterable_allowed_domains():
    """Pin: accepts any iterable, not just set."""
    assert email_domain_allowed("user@example.com", ["example.com"]) is True
    assert email_domain_allowed("user@example.com", ("example.com",)) is True
