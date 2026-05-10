"""HMAC timing-safe compare wrapper (cycle UU3).

Thin wrapper around `hmac.compare_digest` with safe handling of
None / empty / type-mismatched inputs. Used by every signature-
verification path: Y2's `webhook_sig.verify_with_trace`, KK2's
`secret_rotation`, and any future API-key compare.

  safe_compare(a, b)  — bool, constant-time-equal

Pinned invariants:
  * Returns True iff `a == b` for non-None equal-type non-empty
    inputs (delegates to `hmac.compare_digest` for the actual
    constant-time compare).
  * None either side → False (without leaking presence via
    early-return — the function STILL calls `compare_digest`
    with placeholder data to keep the timing profile uniform).
  * Empty either side → False (same uniform-timing pattern).
  * Type mismatch (one bytes, one str) → False (does NOT
    auto-convert — surfaces caller bug).
  * Length mismatch within same type → False (delegates to
    `hmac.compare_digest`, which is constant-time even on
    length mismatch).

Pure stdlib.
"""

from __future__ import annotations

import hmac

# Placeholder bytes used to keep timing uniform when one input
# is None / empty / mismatched. Length matches a typical
# SHA-256 hex digest (64 chars). The actual compare result is
# discarded — the call exists only to keep the timing profile
# from leaking which input was invalid.
_PLACEHOLDER_BYTES = b"\x00" * 64
_PLACEHOLDER_STR = "0" * 64


def safe_compare(
    a: str | bytes | None,
    b: str | bytes | None,
) -> bool:
    """Constant-time-equal compare with safe defaults.

    Returns False for any of:
      * Either input None.
      * Either input empty.
      * Type mismatch (one str, one bytes).

    For valid same-type non-empty inputs, delegates to
    `hmac.compare_digest` which is constant-time across both
    equality and length-mismatch cases.
    """
    # None either side: still call compare_digest to keep timing.
    if a is None or b is None:
        hmac.compare_digest(_PLACEHOLDER_BYTES, _PLACEHOLDER_BYTES)
        return False

    # Type mismatch: hmac.compare_digest raises TypeError on
    # mixed-type inputs. Return False without raising (caller
    # bug surfaces as auth-failed, not 500).
    if type(a) is not type(b):
        hmac.compare_digest(_PLACEHOLDER_BYTES, _PLACEHOLDER_BYTES)
        return False

    # Empty either side: keep timing uniform.
    if not a or not b:
        if isinstance(a, bytes):
            hmac.compare_digest(_PLACEHOLDER_BYTES, _PLACEHOLDER_BYTES)
        else:
            hmac.compare_digest(_PLACEHOLDER_STR, _PLACEHOLDER_STR)
        return False

    # Python 3.13 raises TypeError for non-ASCII strings in
    # compare_digest. Encode both sides to UTF-8 bytes so the
    # constant-time guarantee still holds for Unicode inputs.
    if isinstance(a, str):
        return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))  # type: ignore[union-attr]
    return hmac.compare_digest(a, b)
