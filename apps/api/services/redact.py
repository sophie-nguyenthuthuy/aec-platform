"""Email & phone PII redaction for logs (cycle XX1).

Redact PII from log lines and audit row plaintext exports
before shipping to external aggregators (Sentry, log archives,
Slack alert bodies). Today the structured-log filter and the
audit plaintext-export each redact inline with subtly different
patterns. This module is the single source of truth.

  redact_email(text)       — replaces emails with `[email]`
  redact_phone_vn(text)    — replaces VN mobile numbers with `[phone]`
  redact_pii(text)         — runs both

Pattern alignment:
  * Email regex matches the same shape as GG3's `parse_email`
    validator (local@domain.tld with subdomains).
  * Phone regex matches the same shape as BB2's `parse_phone_vn`
    validator (+84/84/0 prefix + mobile prefix + 8 more digits).

Pinned invariants:
  * Replaces the FULL match; surrounding text preserved.
  * Idempotent: `redact(redact(x)) == redact(x)`.
  * Placeholders `[email]` / `[phone]` themselves don't contain
    `@` or matching digit patterns — won't re-trigger redaction.
  * Multiple matches in same text all redacted.
  * None / empty → "".

Pure stdlib.
"""

from __future__ import annotations

import re

# Email pattern aligned with GG3's structural rules: local part
# alphanumeric + `_%+-` (no leading/trailing dot enforced via
# segment grouping); domain labels alphanumeric + hyphens (no
# leading/trailing); TLD ≥2 chars implied by the +-segments.
_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9_%+\-]+(?:\.[a-zA-Z0-9_%+\-]+)*"
    r"@"
    r"[a-zA-Z0-9](?:[a-zA-Z0-9\-]*[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9\-]*[a-zA-Z0-9])?)+",
)


# VN mobile phone pattern aligned with BB2's `VN_MOBILE_PREFIXES`:
# leading `+84` / `84` / `0`, then mobile-prefix digit (3/5/7/8/9),
# then 8 more digits with optional separators.
_PHONE_VN_RE = re.compile(
    r"(?:\+84|84|0)[\s\-.()]*[35789](?:[\s\-.()]*\d){8}",
)


def redact_email(text: str | None) -> str:
    """Replace email addresses with `[email]`."""
    if not text:
        return ""
    return _EMAIL_RE.sub("[email]", text)


def redact_phone_vn(text: str | None) -> str:
    """Replace VN mobile phone numbers with `[phone]`."""
    if not text:
        return ""
    return _PHONE_VN_RE.sub("[phone]", text)


def redact_pii(text: str | None) -> str:
    """Redact both emails and VN phone numbers.

    Order matters slightly: email first (so a phone number
    inside an email username isn't independently redacted —
    rare but possible).
    """
    if not text:
        return ""
    return redact_phone_vn(redact_email(text))
