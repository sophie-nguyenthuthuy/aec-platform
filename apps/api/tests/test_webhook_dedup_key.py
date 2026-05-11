"""Webhook delivery dedup key generator (cycle QQ1).

Pinned seams:
  1. PAYLOAD_HASH_TRUNCATE_CHARS = 16.
  2. Deterministic — same input always yields same key.
  3. NO timestamps in the input.
  4. subscription_id REQUIRED (cross-tenant guard).
  5. Output 64-char lowercase hex.
  6. Composes with PP1 format_hash_prefix.
"""

from __future__ import annotations

import pytest

from services.format_hash_prefix import format_hash_prefix
from services.webhook_dedup_key import (
    PAYLOAD_HASH_TRUNCATE_CHARS,
    dedup_key,
)

# ---------- Constants ----------


def test_payload_hash_truncate_chars():
    """16 hex chars = 64 bits entropy — collision-resistant at
    AEC scale. Pin so a refactor that bumps to 32 (or drops)
    surfaces — would invalidate existing dedup state in DB."""
    assert PAYLOAD_HASH_TRUNCATE_CHARS == 16


# ---------- Determinism ----------


def test_same_input_same_key():
    a = dedup_key("sub-1", "estimate.create", "est-42", "abc123def4567890extra")
    b = dedup_key("sub-1", "estimate.create", "est-42", "abc123def4567890extra")
    assert a == b


def test_repeat_calls_stable():
    """Pin: 100 calls with same input all yield identical key."""
    keys = {dedup_key("sub-1", "ev", "res", "h1234567890123456") for _ in range(100)}
    assert len(keys) == 1


# ---------- Output format ----------


def test_output_is_64_char_hex():
    key = dedup_key("sub-1", "ev", "res", "h1234567890123456")
    assert len(key) == 64
    assert all(c in "0123456789abcdef" for c in key)


def test_output_lowercase_hex():
    """SHA-256 hexdigest is lowercase by default. Pin so a
    refactor that uppercases would break case-sensitive
    unique-index lookups in the DB."""
    key = dedup_key("sub-1", "ev", "res", "h1234567890123456")
    assert key == key.lower()


# ---------- Variance ----------


def test_different_subscription_different_key():
    """Cardinal pin: cross-tenant uniqueness."""
    a = dedup_key("sub-1", "ev", "res", "h1234567890123456")
    b = dedup_key("sub-2", "ev", "res", "h1234567890123456")
    assert a != b


def test_different_event_type_different_key():
    a = dedup_key("sub-1", "create", "res", "h1234567890123456")
    b = dedup_key("sub-1", "delete", "res", "h1234567890123456")
    assert a != b


def test_different_resource_id_different_key():
    a = dedup_key("sub-1", "ev", "res-1", "h1234567890123456")
    b = dedup_key("sub-1", "ev", "res-2", "h1234567890123456")
    assert a != b


def test_different_payload_hash_first_16_different_key():
    a = dedup_key("sub-1", "ev", "res", "abcdef0123456789")
    b = dedup_key("sub-1", "ev", "res", "abcdef012345678X")
    assert a != b


# ---------- Payload hash truncation ----------


def test_payload_hash_beyond_16_chars_ignored():
    """Cardinal pin: same first-16-chars → same key. Pin against
    a refactor that uses the full payload hash (would change
    every existing dedup key)."""
    a = dedup_key("sub-1", "ev", "res", "abcdef0123456789EXTRA1")
    b = dedup_key("sub-1", "ev", "res", "abcdef0123456789EXTRA2")
    assert a == b  # Same first 16 chars.


def test_payload_hash_first_15_same_chars_16th_differs():
    """Difference at position 15 (within truncate window) →
    different key."""
    a = dedup_key("sub-1", "ev", "res", "abcdef012345678A")
    b = dedup_key("sub-1", "ev", "res", "abcdef012345678B")
    assert a != b


def test_payload_hash_shorter_than_16_works():
    """Short payload_hash (< 16 chars) is fine — caller may pass
    a non-SHA hash."""
    key = dedup_key("sub-1", "ev", "res", "short")
    assert len(key) == 64


def test_payload_hash_empty_works():
    """Empty payload_hash is allowed — broadcast events with no
    payload still get a deterministic key."""
    key = dedup_key("sub-1", "ev", "res", "")
    assert len(key) == 64


# ---------- Required subscription_id ----------


def test_empty_subscription_id_raises():
    """Cardinal pin: subscription_id required. Cross-tenant
    dedup is a security risk — pin against a refactor that
    accepts None / empty."""
    with pytest.raises(ValueError):
        dedup_key("", "ev", "res", "h1234567890123456")


def test_other_fields_can_be_empty():
    """event_type, resource_id, payload_hash all allowed empty
    (broadcast events, etc)."""
    key = dedup_key("sub-1", "", "", "")
    assert len(key) == 64


# ---------- No timestamp dependence ----------


def test_no_timestamp_in_key():
    """Cardinal pin: dedup ignores time. A retry after backoff
    is the SAME logical event — must produce the same key."""
    # Two calls with same input across (hypothetical) time
    # boundary yield identical keys. Trivially true if the
    # function takes no time arg, but pin via direct comparison.
    key1 = dedup_key("sub-1", "ev", "res", "h1234567890123456")
    # ... time passes ...
    key2 = dedup_key("sub-1", "ev", "res", "h1234567890123456")
    assert key1 == key2


# ---------- Composition with PP1 ----------


def test_composes_with_pp1_format_hash_prefix():
    """Cross-cycle pin: dedup key is hex, so PP1's hash-prefix
    formatter renders it cleanly for log lines."""
    key = dedup_key("sub-1", "ev", "res", "h1234567890123456")
    display = format_hash_prefix(key)
    assert "…" in display
    # 7 hex chars + 1 ellipsis.
    assert len(display) == 8


def test_composes_with_pp1_custom_length():
    key = dedup_key("sub-1", "ev", "res", "h1234567890123456")
    display = format_hash_prefix(key, length=12)
    assert len(display) == 13  # 12 + ellipsis
