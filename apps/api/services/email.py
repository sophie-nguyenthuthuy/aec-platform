"""Email validation (cycle GG3, Python half).

Server-side mirror of `apps/web/lib/email.ts`. Used by:

  * The org-create endpoint validator (rejects malformed
    owner-email with HTTP 422).
  * The notification preference seeder (canonicalises to
    lowercased form before storing).
  * The audit row's email-impact detector — actions that emit
    an email reference get a different tone class.
  * The CSV / pinned-export columns where email columns appear.

  parse_email(input)       — lowercased canonical or None
  is_valid_email(input)    — bool
  email_domain(input)      — lowercased domain or None
  MAX_EMAIL_LENGTH         — 254 (RFC 5321)
  MAX_LOCAL_PART_LENGTH    — 64

Storage convention: emails stored lowercased. Pin so a refactor
that preserves user-typed case introduces a duplicate-row risk
(the audit_row.actor_email column has a unique constraint).

Out of scope: quoted local parts, IDN domains, IP-literal hosts.
Pure ASCII.

Pure stdlib.
"""

from __future__ import annotations

import re

# RFC 5321 §4.5.3.1.3.
MAX_EMAIL_LENGTH = 254


# RFC 5321 §4.5.3.1.1.
MAX_LOCAL_PART_LENGTH = 64


# Local part: alphanumeric + . _ % + - (no leading/trailing dot,
# no consecutive dots — enforced via segment grouping).
_LOCAL_PART_RE = re.compile(r"^[a-zA-Z0-9_%+\-]+(?:\.[a-zA-Z0-9_%+\-]+)*$")


# Domain label: alphanumeric + hyphen, NOT leading/trailing hyphen
# (RFC 1035 LDH).
_DOMAIN_LABEL_RE = re.compile(r"^[a-zA-Z0-9](?:[a-zA-Z0-9\-]*[a-zA-Z0-9])?$")


def parse_email(input_str: str | None) -> str | None:
    """Parse and lowercase-canonicalize an email address.

    Returns canonical `local@domain` (lowercased) or None.
    """
    if input_str is None:
        return None
    s = input_str.strip()
    if not s:
        return None
    if len(s) > MAX_EMAIL_LENGTH:
        return None

    parts = s.split("@")
    if len(parts) != 2:
        return None
    local, domain = parts

    if not local or len(local) > MAX_LOCAL_PART_LENGTH:
        return None
    if not _LOCAL_PART_RE.match(local):
        return None

    if not domain:
        return None
    if domain.startswith(".") or domain.endswith("."):
        return None
    if ".." in domain:
        return None
    if "." not in domain:
        return None

    labels = domain.split(".")
    for label in labels:
        if not _DOMAIN_LABEL_RE.match(label):
            return None

    # TLD must be ≥2 chars (rules out single-letter TLDs and
    # the bare-hostname-with-trailing-dot case).
    if len(labels[-1]) < 2:
        return None

    return f"{local.lower()}@{domain.lower()}"


def is_valid_email(input_str: str | None) -> bool:
    """True iff `parse_email(input)` returns non-None."""
    return parse_email(input_str) is not None


def email_domain(input_str: str | None) -> str | None:
    """Return the lowercased domain part, or None if invalid.

    Used by the audit row's domain-grouping aggregator and the
    notification dispatcher's per-domain rate limiter.
    """
    parsed = parse_email(input_str)
    if parsed is None:
        return None
    return parsed.split("@", 1)[1]
