"""HTTP Authorization header builder (cycle SS2).

Inverse of JJ3's `parse_auth_header`. Today the webhook
delivery worker, the audit endpoint's bearer-token client, and
the rotation-grace verifier each construct headers inline with
subtly different scheme capitalization. This module is the
single source of truth.

  build_auth_header(scheme, value)  — "Bearer abc" / "Basic ..." / "HMAC-SHA256 ..."

Round-trip stable with JJ3 (`parse → build → parse` preserves
the AuthHeader shape).

Pinned invariants:
  * Scheme validated against JJ3's `KNOWN_SCHEMES` (rejects
    unknown — same closed set).
  * Output uses HTTP wire-format capitalization:
    - `bearer` → `Bearer`
    - `basic`  → `Basic`
    - `hmac-sha256` → `HMAC-SHA256` (all-caps acronym)
  * Empty value → ValueError.
  * Empty scheme → ValueError.

Pure stdlib + JJ3 (KNOWN_SCHEMES import).
"""

from __future__ import annotations

from services.auth_header import KNOWN_SCHEMES


def build_auth_header(scheme: str, value: str) -> str:
    """Build an `Authorization: <scheme> <value>` header value.

    `scheme` accepts any case and is normalized to the canonical
    HTTP wire format on output.

    Raises:
      * ValueError if scheme is empty or unknown.
      * ValueError if value is empty.
    """
    if not scheme:
        raise ValueError("scheme is required")
    scheme_lower = scheme.lower()
    if scheme_lower not in KNOWN_SCHEMES:
        raise ValueError(f"unknown scheme: {scheme!r} (must be one of {sorted(KNOWN_SCHEMES)})")
    if not value:
        raise ValueError("value is required")

    # HTTP wire-format capitalization.
    scheme_out = "HMAC-SHA256" if scheme_lower == "hmac-sha256" else scheme_lower.capitalize()

    return f"{scheme_out} {value}"
