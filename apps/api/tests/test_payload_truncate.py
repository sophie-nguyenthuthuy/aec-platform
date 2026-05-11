"""Webhook payload truncation (cycle JJ1).

Pinned seams:
  1. DEFAULT_MAX_PAYLOAD_BYTES = 65536 (64KB).
  2. PER_FIELD_STRING_LIMIT = 1024 (1KB).
  3. TRUNCATION_MARKER_PREFIX = "[truncated:".
  4. Truncation marker shows ORIGINAL byte size.
  5. Idempotent on already-truncated input.
  6. Type-shape preserved (truncated string stays string).
  7. Dict iteration sorted (deterministic).
  8. Top-level sentinel when whole payload exceeds limit.
"""

from __future__ import annotations

from services.payload_truncate import (
    DEFAULT_MAX_PAYLOAD_BYTES,
    PER_FIELD_STRING_LIMIT,
    TRUNCATION_MARKER_PREFIX,
    truncate_payload,
)

# ---------- Constants ----------


def test_default_max_payload_bytes_is_64kb():
    """Pin so a refactor that drops to e.g. 16KB silently
    truncates legitimate webhook payloads."""
    assert DEFAULT_MAX_PAYLOAD_BYTES == 65536


def test_per_field_string_limit_is_1kb():
    assert PER_FIELD_STRING_LIMIT == 1024


def test_truncation_marker_prefix():
    assert TRUNCATION_MARKER_PREFIX == "[truncated:"


# ---------- Pass-through (under limit) ----------


def test_none_returns_none():
    assert truncate_payload(None) is None


def test_empty_dict_returns_empty_dict():
    assert truncate_payload({}) == {}


def test_empty_list_returns_empty_list():
    assert truncate_payload([]) == []


def test_small_payload_passes_through_unchanged():
    payload = {"action": "pulse.change_order.approve", "id": 42}
    assert truncate_payload(payload) == payload


def test_short_string_passes_through():
    payload = {"description": "Short text"}
    assert truncate_payload(payload) == payload


def test_scalars_pass_through():
    """Non-dict/list scalars at top level pass through (an
    unusual but possible payload shape)."""
    assert truncate_payload(42) == 42
    assert truncate_payload(True) is True
    assert truncate_payload("short") == "short"


# ---------- Per-field string truncation ----------


def test_long_string_replaced_with_marker():
    """String over PER_FIELD_STRING_LIMIT becomes marker."""
    long_string = "x" * 2000
    payload = {"body": long_string}
    result = truncate_payload(payload)
    assert result["body"] == f"{TRUNCATION_MARKER_PREFIX}2000]"


def test_marker_shows_original_byte_size():
    """Pin: marker contains ORIGINAL size, not the truncated
    form size. Caller uses this to display "truncated from N
    bytes" in the dashboard."""
    payload = {"body": "a" * 5000}
    result = truncate_payload(payload)
    assert result["body"] == f"{TRUNCATION_MARKER_PREFIX}5000]"


def test_string_at_limit_passes_through():
    """Boundary: string EXACTLY at PER_FIELD_STRING_LIMIT does
    NOT get truncated (the limit is strict <)."""
    string_at_limit = "x" * PER_FIELD_STRING_LIMIT
    payload = {"body": string_at_limit}
    result = truncate_payload(payload)
    # Below the whole-payload max so passes through as-is.
    assert result["body"] == string_at_limit


def test_string_one_byte_over_limit_truncated():
    over = "x" * (PER_FIELD_STRING_LIMIT + 1)
    payload = {"body": over}
    result = truncate_payload(payload)
    assert result["body"] == f"{TRUNCATION_MARKER_PREFIX}{PER_FIELD_STRING_LIMIT + 1}]"


def test_short_string_in_same_payload_unchanged():
    """Pin: only oversize strings are touched. Short strings in
    the same payload preserve their original content."""
    payload = {
        "id": "abc123",
        "body": "y" * 2000,
    }
    result = truncate_payload(payload)
    assert result["id"] == "abc123"
    assert result["body"] == f"{TRUNCATION_MARKER_PREFIX}2000]"


# ---------- Type-shape preservation ----------


def test_truncated_string_stays_string():
    """Cardinal pin: a truncated string field stays a string,
    NOT replaced with null or a sentinel object. Defends against
    a refactor that breaks downstream type validation."""
    payload = {"body": "z" * 2000}
    result = truncate_payload(payload)
    assert isinstance(result["body"], str)


def test_int_field_preserved():
    payload = {"count": 42, "body": "y" * 2000}
    result = truncate_payload(payload)
    assert result["count"] == 42


def test_bool_field_preserved():
    payload = {"enabled": True, "body": "z" * 2000}
    result = truncate_payload(payload)
    assert result["enabled"] is True


def test_null_field_preserved():
    payload = {"reason": None, "body": "z" * 2000}
    result = truncate_payload(payload)
    assert result["reason"] is None


# ---------- Nested ----------


def test_nested_dict_traversed():
    payload = {"outer": {"inner": "y" * 2000}}
    result = truncate_payload(payload)
    assert result["outer"]["inner"] == f"{TRUNCATION_MARKER_PREFIX}2000]"


def test_nested_list_traversed():
    payload = {"items": ["short", "y" * 2000, "also short"]}
    result = truncate_payload(payload)
    assert result["items"][0] == "short"
    assert result["items"][1] == f"{TRUNCATION_MARKER_PREFIX}2000]"
    assert result["items"][2] == "also short"


def test_deeply_nested_traversed():
    payload = {"a": {"b": {"c": [{"d": "z" * 2000}]}}}
    result = truncate_payload(payload)
    assert result["a"]["b"]["c"][0]["d"] == f"{TRUNCATION_MARKER_PREFIX}2000]"


# ---------- Idempotency ----------


def test_idempotent_on_already_truncated_string():
    """Pin: re-truncating an already-truncated string returns it
    verbatim. A refactor that wraps the marker again would
    produce `[truncated:[truncated:N]]` — surface here."""
    pre_truncated = f"{TRUNCATION_MARKER_PREFIX}5000]"
    payload = {"body": pre_truncated}
    result = truncate_payload(payload)
    assert result["body"] == pre_truncated


def test_idempotent_on_full_truncated_payload():
    """Re-truncating a truncated payload yields the same result."""
    original = {"body": "y" * 2000}
    once = truncate_payload(original)
    twice = truncate_payload(once)
    assert twice == once


# ---------- Determinism ----------


def test_dict_iteration_sorted():
    """Pin: keys appear in sorted order. Snapshot tests upstream
    rely on this."""
    payload = {"b": "y" * 2000, "a": "z" * 2000}
    result = truncate_payload(payload)
    keys = list(result.keys())
    assert keys == sorted(keys)


# ---------- Top-level sentinel ----------


def test_top_level_sentinel_when_too_large_after_truncation():
    """Many small strings, none individually over PER_FIELD limit,
    but total exceeds max_bytes. Returns sentinel."""
    payload = {f"key_{i}": "x" * 500 for i in range(200)}
    result = truncate_payload(payload, max_bytes=10000)
    assert result["_truncated_kind"] == "payload"
    assert result["_max_bytes"] == 10000
    assert result["_original_size"] > 10000


def test_top_level_sentinel_includes_original_size():
    """Pin: sentinel includes diagnostic original size."""
    payload = {f"k{i}": "x" * 500 for i in range(300)}
    result = truncate_payload(payload, max_bytes=5000)
    assert "_original_size" in result
    assert result["_original_size"] > result["_max_bytes"]


# ---------- Custom max_bytes ----------


def test_custom_max_bytes_respected():
    """A small max_bytes triggers truncation even for modest
    payloads."""
    payload = {"body": "x" * 100}
    # At max_bytes=10, the small payload exceeds. But the string
    # is under PER_FIELD_STRING_LIMIT so won't be string-truncated.
    # Falls back to top-level sentinel.
    result = truncate_payload(payload, max_bytes=10)
    assert result["_truncated_kind"] == "payload"
