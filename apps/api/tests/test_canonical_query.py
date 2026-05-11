"""HTTP query string canonical builder (cycle PP3).

Pinned seams:
  1. Keys sorted alphabetically.
  2. Empty dict → "".
  3. None values OMITTED.
  4. Empty-string values INCLUDED as `key=` (distinct from None).
  5. List values become repeated keys preserving order.
  6. RFC 3986 encoding (space → %20).
  7. Bool → `true` / `false` (lowercased).
"""

from __future__ import annotations

from services.canonical_query import build_canonical_query

# ---------- Empty / basic ----------


def test_empty_dict():
    assert build_canonical_query({}) == ""


def test_single_pair():
    assert build_canonical_query({"a": "1"}) == "a=1"


def test_two_pairs_sorted():
    """Cardinal pin: keys sorted alphabetically. Pin against
    Python dict-iteration variance pre-3.7 (and against
    accidentally relying on insertion order)."""
    assert build_canonical_query({"b": "2", "a": "1"}) == "a=1&b=2"


def test_many_keys_sorted():
    assert build_canonical_query({"c": "3", "a": "1", "b": "2"}) == "a=1&b=2&c=3"


# ---------- None handling ----------


def test_none_value_omitted():
    """Cardinal pin: None values DROPPED entirely (not `key=None`)."""
    assert build_canonical_query({"a": None}) == ""
    assert build_canonical_query({"a": None, "b": "2"}) == "b=2"


def test_empty_string_value_included():
    """Cardinal pin: empty string is DISTINCT from None — emits
    `key=` to preserve the user's intent (e.g., `?q=` to
    explicitly clear a filter)."""
    assert build_canonical_query({"a": ""}) == "a="
    assert build_canonical_query({"a": "", "b": "2"}) == "a=&b=2"


# ---------- List values ----------


def test_list_becomes_repeated_keys():
    assert build_canonical_query({"tags": ["a", "b"]}) == "tags=a&tags=b"


def test_list_preserves_order():
    """Pin: list element order preserved (NOT alphabetized).
    The list represents the user's input order — sorting would
    silently change semantics for ordered tags."""
    assert build_canonical_query({"tags": ["c", "a", "b"]}) == "tags=c&tags=a&tags=b"


def test_list_with_none_element_skipped():
    assert build_canonical_query({"tags": ["a", None, "b"]}) == "tags=a&tags=b"


def test_empty_list_emits_nothing():
    """Empty list → no key emitted (parallel to None)."""
    assert build_canonical_query({"tags": []}) == ""


def test_list_with_only_none_emits_nothing():
    assert build_canonical_query({"tags": [None, None]}) == ""


def test_list_with_mixed_keys():
    """Two keys, one a list — both alphabetized at top level,
    list maintains internal order."""
    result = build_canonical_query({"tags": ["a", "b"], "name": "x"})
    assert result == "name=x&tags=a&tags=b"


# ---------- Encoding ----------


def test_space_encoded_as_percent_20():
    """Pin: space → %20 (RFC 3986), NOT `+` (HTML form encoding)."""
    assert build_canonical_query({"q": "hello world"}) == "q=hello%20world"


def test_special_chars_encoded():
    """Special chars encoded per RFC 3986."""
    assert build_canonical_query({"k": "a&b=c"}) == "k=a%26b%3Dc"


def test_unicode_encoded():
    """Vietnamese chars encoded as UTF-8 percent escapes."""
    assert build_canonical_query({"name": "Hà Nội"}) == "name=H%C3%A0%20N%E1%BB%99i"


def test_key_with_special_chars_encoded():
    """Pin: keys also percent-encoded."""
    assert build_canonical_query({"a key": "1"}) == "a%20key=1"


# ---------- Bool values ----------


def test_bool_true_lowercased():
    """Cardinal pin: bool True → `true` (lowercased), NOT
    Python's `True` repr."""
    assert build_canonical_query({"x": True}) == "x=true"


def test_bool_false_lowercased():
    assert build_canonical_query({"x": False}) == "x=false"


# ---------- Numeric values ----------


def test_int_value():
    assert build_canonical_query({"n": 42}) == "n=42"


def test_zero_value():
    assert build_canonical_query({"n": 0}) == "n=0"


def test_negative_value():
    assert build_canonical_query({"n": -5}) == "n=-5"


def test_float_value():
    assert build_canonical_query({"x": 3.14}) == "x=3.14"


# ---------- Determinism (pin for HMAC use) ----------


def test_determinism_same_input_same_output():
    """Cardinal pin: foundational for Y2 webhook signing. Same
    input → same output across multiple calls."""
    params = {"action": "create", "resource": "estimate", "id": 42}
    a = build_canonical_query(params)
    b = build_canonical_query(params)
    assert a == b


def test_determinism_input_order_irrelevant():
    """Insertion order doesn't affect output (sorted keys)."""
    a = build_canonical_query({"b": "2", "a": "1", "c": "3"})
    b = build_canonical_query({"a": "1", "b": "2", "c": "3"})
    c = build_canonical_query({"c": "3", "b": "2", "a": "1"})
    assert a == b == c


# ---------- Realistic shapes ----------


def test_realistic_audit_filter_query():
    """A realistic audit-page filter query."""
    params = {
        "since": "2026-01-01",
        "actor": "user@example.com",
        "modules": ["pulse", "submittals"],
        "page": 1,
    }
    result = build_canonical_query(params)
    assert result == ("actor=user%40example.com&modules=pulse&modules=submittals&page=1&since=2026-01-01")
