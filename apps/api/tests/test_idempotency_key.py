"""HTTP Idempotency-Key header validator (cycle HH3).

Pinned seams:
  1. MIN_IDEMPOTENCY_KEY_LENGTH = 16 (anti-guess floor).
  2. MAX_IDEMPOTENCY_KEY_LENGTH = 128 (DoS guard).
  3. URL-safe char class only: [a-zA-Z0-9_-].
  4. Lowercased canonical on storage.
  5. Whitespace internally → rejected (boundary stripped).
  6. UUID v4 format passes (case-insensitive).
  7. None / empty → None.
"""

from __future__ import annotations

from services.idempotency_key import (
    MAX_IDEMPOTENCY_KEY_LENGTH,
    MIN_IDEMPOTENCY_KEY_LENGTH,
    is_valid_idempotency_key,
    parse_idempotency_key,
)

# ---------- Constants ----------


def test_min_length_is_16():
    """Anti-guess floor — 16 chars in [a-zA-Z0-9] gives ~95 bits
    of entropy, well above the ~64 bits at which exhaustive
    search becomes feasible. Pin so a refactor that drops to e.g.
    8 silently weakens replay protection."""
    assert MIN_IDEMPOTENCY_KEY_LENGTH == 16


def test_max_length_is_128():
    """DoS guard. Pin so a refactor that bumps to e.g. 1024
    surfaces in review."""
    assert MAX_IDEMPOTENCY_KEY_LENGTH == 128


# ---------- Length boundaries ----------


def test_accepts_at_min_length():
    key = "a" * 16
    assert parse_idempotency_key(key) == key


def test_rejects_below_min_length():
    assert parse_idempotency_key("a" * 15) is None
    assert parse_idempotency_key("short") is None


def test_accepts_at_max_length():
    key = "a" * 128
    assert parse_idempotency_key(key) == key


def test_rejects_above_max_length():
    assert parse_idempotency_key("a" * 129) is None


# ---------- UUID v4 ----------


def test_accepts_uuid_v4_lowercase():
    uuid = "550e8400-e29b-41d4-a716-446655440000"
    assert parse_idempotency_key(uuid) == uuid


def test_accepts_uuid_v4_uppercase_lowercases_it():
    """Cardinal pin: case-insensitive dedup. A UUID submitted
    in either case must dedupe against the same key."""
    upper = "550E8400-E29B-41D4-A716-446655440000"
    lower = "550e8400-e29b-41d4-a716-446655440000"
    assert parse_idempotency_key(upper) == lower


def test_uuid_v4_round_trips_canonical():
    uuid = "550e8400-e29b-41d4-a716-446655440000"
    canonical = parse_idempotency_key(uuid)
    assert canonical is not None
    # Re-parsing the canonical yields the same canonical (idempotent).
    assert parse_idempotency_key(canonical) == canonical


# ---------- Character class ----------


def test_accepts_alphanumeric_only():
    key = "abcdefghij1234567890"
    assert parse_idempotency_key(key) == key


def test_accepts_underscore_and_hyphen():
    key = "namespace_key-with_segments"
    assert parse_idempotency_key(key) == key


def test_rejects_whitespace_internal():
    """Pin: internal whitespace → rejected. A key with internal
    whitespace is a client bug worth surfacing (likely a
    serialization mistake)."""
    assert parse_idempotency_key("key with spaces here") is None
    assert parse_idempotency_key("key\twith\ttabs") is None


def test_rejects_special_chars():
    """Pin URL-safe: rejects slashes, dots, plus, etc."""
    assert parse_idempotency_key("key/with/slashes") is None
    assert parse_idempotency_key("key.with.dots1234") is None
    assert parse_idempotency_key("key+plus+signs+1234") is None
    assert parse_idempotency_key("key@with@at@signs") is None


def test_rejects_punctuation():
    assert parse_idempotency_key("key!exclamation12345") is None
    assert parse_idempotency_key("key:colon:separated123") is None


# ---------- Whitespace boundary ----------


def test_strips_leading_trailing_whitespace_before_validation():
    """Boundary whitespace is stripped before length / charset
    validation. A 16-char key with surrounding whitespace passes."""
    key = "abcdefghijklmnop"
    assert parse_idempotency_key(f"  {key}  ") == key


def test_whitespace_only_rejected():
    assert parse_idempotency_key("   ") is None


# ---------- Case folding ----------


def test_case_folds_to_lowercase():
    """Cardinal pin: dedup is case-insensitive. A refactor that
    preserves case introduces a duplicate-key risk."""
    assert parse_idempotency_key("UPPER_LOWER_12345") == "upper_lower_12345"


def test_case_folds_mixed_case():
    assert parse_idempotency_key("MixedCase_1234567") == "mixedcase_1234567"


# ---------- None / empty ----------


def test_returns_none_for_none():
    assert parse_idempotency_key(None) is None


def test_returns_none_for_empty():
    assert parse_idempotency_key("") is None


# ---------- is_valid_idempotency_key ----------


def test_is_valid_for_valid_key():
    assert is_valid_idempotency_key("550e8400-e29b-41d4-a716-446655440000") is True


def test_is_invalid_for_short():
    assert is_valid_idempotency_key("short") is False


def test_is_invalid_for_none():
    assert is_valid_idempotency_key(None) is False
    assert is_valid_idempotency_key("") is False
