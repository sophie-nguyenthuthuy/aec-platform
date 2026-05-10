"""Pagination cursor encoder/decoder (cycle VV3).

Pinned seams:
  1. None Cursor → "" string.
  2. Empty / None string → None Cursor.
  3. URL-safe base64 (no `+/=`).
  4. Deterministic encoding (sort_keys=True).
  5. Round-trip stable.
  6. Malformed → None.
  7. Type validation on decode.
"""

from __future__ import annotations

from services.pagination_cursor import Cursor, decode_cursor, encode_cursor

# ---------- Encode ----------


def test_encode_none_returns_empty():
    assert encode_cursor(None) == ""


def test_encode_simple_cursor():
    c = Cursor(last_id="42", last_sort_value="2026-01-01")
    encoded = encode_cursor(c)
    assert encoded != ""
    assert isinstance(encoded, str)


def test_encode_int_id():
    c = Cursor(last_id=42, last_sort_value=100)
    assert encode_cursor(c) != ""


def test_encode_url_safe_no_special_chars():
    """Cardinal pin: URL-safe base64. No `+/=` chars."""
    c = Cursor(last_id="long-id-that-exercises-encoding-bytes", last_sort_value=12345)
    encoded = encode_cursor(c)
    assert "+" not in encoded
    assert "/" not in encoded
    assert "=" not in encoded


def test_encode_deterministic():
    """Same input → same encoded output (sort_keys + stable JSON)."""
    c = Cursor(last_id="42", last_sort_value="abc")
    a = encode_cursor(c)
    b = encode_cursor(c)
    assert a == b


def test_encode_with_none_sort_value():
    c = Cursor(last_id="42", last_sort_value=None)
    encoded = encode_cursor(c)
    assert encoded != ""
    assert decode_cursor(encoded) == c


def test_encode_with_bool_sort_value():
    c = Cursor(last_id="42", last_sort_value=True)
    encoded = encode_cursor(c)
    decoded = decode_cursor(encoded)
    assert decoded == c


def test_encode_with_float_sort_value():
    c = Cursor(last_id="42", last_sort_value=3.14)
    encoded = encode_cursor(c)
    decoded = decode_cursor(encoded)
    assert decoded == c


# ---------- Decode ----------


def test_decode_empty_returns_none():
    assert decode_cursor("") is None


def test_decode_none_returns_none():
    assert decode_cursor(None) is None


def test_decode_garbage_returns_none():
    assert decode_cursor("not-base64") is None


def test_decode_malformed_base64_returns_none():
    assert decode_cursor("!@#$%") is None


def test_decode_valid_base64_but_not_json_returns_none():
    """`aGVsbG8` is base64 of "hello" — not JSON."""
    assert decode_cursor("aGVsbG8") is None


def test_decode_valid_json_but_not_dict_returns_none():
    """A JSON array (not dict) → None."""
    import base64

    encoded = base64.urlsafe_b64encode(b"[1,2,3]").rstrip(b"=").decode("ascii")
    assert decode_cursor(encoded) is None


def test_decode_dict_missing_id_returns_none():
    import base64

    encoded = base64.urlsafe_b64encode(b'{"v": 42}').rstrip(b"=").decode("ascii")
    assert decode_cursor(encoded) is None


def test_decode_dict_missing_v_returns_none():
    import base64

    encoded = base64.urlsafe_b64encode(b'{"id": "x"}').rstrip(b"=").decode("ascii")
    assert decode_cursor(encoded) is None


def test_decode_invalid_id_type_returns_none():
    """`id` must be str or int. List → None."""
    import base64

    encoded = base64.urlsafe_b64encode(b'{"id": [1,2], "v": null}').rstrip(b"=").decode("ascii")
    assert decode_cursor(encoded) is None


def test_decode_bool_id_returns_none():
    """Pin: bool is subclass of int but NOT valid as last_id.
    Defends against subtle bool-as-int leak."""
    import base64

    encoded = base64.urlsafe_b64encode(b'{"id": true, "v": null}').rstrip(b"=").decode("ascii")
    assert decode_cursor(encoded) is None


def test_decode_invalid_sort_value_type_returns_none():
    """sort_value must be a scalar (str/int/float/bool/None).
    Dict → None."""
    import base64

    encoded = base64.urlsafe_b64encode(b'{"id": "x", "v": {"nested": 1}}').rstrip(b"=").decode("ascii")
    assert decode_cursor(encoded) is None


# ---------- Round-trip ----------


def test_round_trip_str_id():
    c = Cursor(last_id="audit-row-42", last_sort_value="2026-05-10")
    assert decode_cursor(encode_cursor(c)) == c


def test_round_trip_int_id():
    c = Cursor(last_id=12345, last_sort_value=999)
    assert decode_cursor(encode_cursor(c)) == c


def test_round_trip_none_sort():
    c = Cursor(last_id="42", last_sort_value=None)
    assert decode_cursor(encode_cursor(c)) == c


def test_round_trip_unicode_id():
    """Vietnamese chars in cursor (rare but possible — e.g.
    paginating over a string-sorted Vietnamese name list)."""
    c = Cursor(last_id="nguyễn-42", last_sort_value="Hà Nội")
    assert decode_cursor(encode_cursor(c)) == c


# ---------- Cursor frozen ----------


def test_cursor_is_frozen():
    c = Cursor(last_id="42", last_sort_value="abc")
    try:
        c.last_id = "100"  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("Cursor should be frozen")


# ---------- Realistic ----------


def test_realistic_audit_pagination():
    """Audit list paginates by (created_at desc, id desc).
    Cursor encodes the last row's id + created_at."""
    c = Cursor(last_id="aud-12345", last_sort_value="2026-05-10T12:00:00Z")
    encoded = encode_cursor(c)
    # URL-safe.
    assert "+" not in encoded
    assert "/" not in encoded
    # Round-trip.
    assert decode_cursor(encoded) == c


def test_realistic_member_pagination():
    """Member list paginates by (joined_at desc, id desc)."""
    c = Cursor(last_id="member-42", last_sort_value=1715332800)  # unix ts
    assert decode_cursor(encode_cursor(c)) == c
