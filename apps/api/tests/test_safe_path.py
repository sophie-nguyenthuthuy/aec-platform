"""File path safety validator (cycle ZZ1).

Pinned seams:
  1. `..` traversal REJECTED.
  2. Absolute paths REJECTED.
  3. Null bytes REJECTED.
  4. URL-encoded escapes REJECTED.
  5. Backslashes REJECTED.
  6. Empty / `.` REJECTED.
"""

from __future__ import annotations

from services.safe_path import is_safe_subpath, safe_join

# ---------- Safe paths ----------


def test_simple_filename_safe():
    assert is_safe_subpath("/base", "photo.jpg") is True


def test_subdirectory_safe():
    assert is_safe_subpath("/base", "images/photo.jpg") is True


def test_deep_subdirectory_safe():
    assert is_safe_subpath("/base", "a/b/c/d/file.txt") is True


def test_dot_slash_prefix_safe():
    """`./foo` normalizes to `foo` — safe."""
    assert is_safe_subpath("/base", "./foo") is True


def test_internal_dot_dot_normalizes_safe():
    """`foo/../bar` normalizes to `bar` — safe."""
    assert is_safe_subpath("/base", "foo/../bar") is True


# ---------- Traversal rejected ----------


def test_dot_dot_at_start_rejected():
    """Cardinal pin: `../etc/passwd` REJECTED."""
    assert is_safe_subpath("/base", "../etc/passwd") is False


def test_double_dot_dot_rejected():
    assert is_safe_subpath("/base", "../../etc/passwd") is False


def test_dot_dot_through_subdir_rejected():
    """`foo/../../etc/passwd` normalizes to `../etc/passwd` —
    rejected."""
    assert is_safe_subpath("/base", "foo/../../etc/passwd") is False


def test_bare_dot_dot_rejected():
    assert is_safe_subpath("/base", "..") is False


# ---------- Absolute paths ----------


def test_absolute_path_rejected():
    """Cardinal pin: absolute paths REJECTED. Must be relative
    to base."""
    assert is_safe_subpath("/base", "/etc/passwd") is False


def test_absolute_root_rejected():
    assert is_safe_subpath("/base", "/") is False


# ---------- Null byte ----------


def test_null_byte_rejected():
    """Cardinal pin: null bytes REJECTED. Defends against
    C-string truncation in downstream tools (e.g.
    `photo.jpg\\x00.exe` becomes `photo.jpg` in some libs)."""
    assert is_safe_subpath("/base", "photo.jpg\x00.exe") is False


def test_null_byte_at_start():
    assert is_safe_subpath("/base", "\x00.txt") is False


# ---------- URL encoding ----------


def test_url_encoded_dot_dot_rejected():
    """Cardinal pin: %2e (encoded `.`) REJECTED. Defends against
    callers that forget to URL-decode."""
    assert is_safe_subpath("/base", "%2e%2e/etc/passwd") is False


def test_url_encoded_slash_rejected():
    """%2f (encoded `/`) REJECTED."""
    assert is_safe_subpath("/base", "foo%2f..%2fetc") is False


def test_url_encoded_backslash_rejected():
    """%5c (encoded `\\`) REJECTED."""
    assert is_safe_subpath("/base", "foo%5cbar") is False


def test_url_encoded_case_insensitive():
    """%2E and %2e both rejected."""
    assert is_safe_subpath("/base", "%2E%2E/etc") is False
    assert is_safe_subpath("/base", "%2e%2e/etc") is False


# ---------- Backslash ----------


def test_backslash_rejected():
    """Cardinal pin: backslashes REJECTED. Defends against
    cross-OS confusion (Windows interprets `..\\` as separator)."""
    assert is_safe_subpath("/base", "..\\etc") is False
    assert is_safe_subpath("/base", "foo\\bar") is False


# ---------- Empty / degenerate ----------


def test_empty_candidate_rejected():
    assert is_safe_subpath("/base", "") is False


def test_whitespace_candidate_rejected():
    assert is_safe_subpath("/base", "   ") is False


def test_dot_only_rejected():
    """`.` (current dir) is degenerate — rejected."""
    assert is_safe_subpath("/base", ".") is False


def test_empty_base_rejected():
    assert is_safe_subpath("", "foo") is False


def test_none_inputs_rejected():
    assert is_safe_subpath(None, "foo") is False
    assert is_safe_subpath("/base", None) is False
    assert is_safe_subpath(None, None) is False


# ---------- safe_join ----------


def test_safe_join_returns_full_path():
    assert safe_join("/base", "photo.jpg") == "/base/photo.jpg"


def test_safe_join_normalizes():
    assert safe_join("/base", "foo/../bar.txt") == "/base/bar.txt"


def test_safe_join_returns_none_for_unsafe():
    assert safe_join("/base", "../etc/passwd") is None
    assert safe_join("/base", "/absolute") is None


def test_safe_join_none_for_empty():
    assert safe_join("/base", "") is None
    assert safe_join("", "foo") is None


# ---------- Realistic ----------


def test_realistic_upload_filename():
    """Realistic: photo upload to project's attachments dir."""
    result = safe_join(
        "/uploads/org_acme/project_42/attachments",
        "photo.jpg",
    )
    assert result == "/uploads/org_acme/project_42/attachments/photo.jpg"


def test_realistic_traversal_attack_blocked():
    """Realistic: malicious upload trying to escape."""
    result = safe_join(
        "/uploads/org_acme/project_42/attachments",
        "../../../../etc/passwd",
    )
    assert result is None
