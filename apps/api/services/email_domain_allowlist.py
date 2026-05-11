"""Email domain allowlist validator (cycle YY3).

Validate that an email's domain matches an allowed-domain set.
Used by:

  * The org-invite-create flow ("only `@vingroup.com.vn` can
    join Vingroup org").
  * The SSO email-claim verifier.
  * The org-create owner-email check.

  email_domain_allowed(email, allowed_domains)  — bool

Composes with GG3's `email_domain` (which validates email
structure AND extracts the lowercased domain).

Pinned invariants:
  * Empty `allowed_domains` set → True (no restriction). Pin
    so unconfigured orgs accept any valid email.
  * Invalid email (GG3 returns None) → False (defends against
    malformed bypass).
  * Case-insensitive domain comparison.
  * EXACT domain match (no wildcard subdomains —
    `user@mail.company.com` does NOT match allowed `company.com`
    unless `mail.company.com` is explicitly listed).

Pure stdlib + GG3.
"""

from __future__ import annotations

from collections.abc import Iterable

from services.email import email_domain


def email_domain_allowed(
    email: str | None,
    allowed_domains: Iterable[str],
) -> bool:
    """True iff `email`'s domain matches an allowed domain.

    Empty `allowed_domains` → True (no restriction).
    Invalid email → False.
    """
    domain = email_domain(email)
    if domain is None:
        return False

    # Normalize allowed domains: strip + lowercase + drop empties.
    normalized = {d.strip().lower() for d in allowed_domains if d and d.strip()}

    # Empty set after normalization = no restriction.
    if not normalized:
        return True

    return domain in normalized
