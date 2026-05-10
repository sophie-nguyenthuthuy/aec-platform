"""HTTP redirect target URL canonicalizer (cycle SS1).

Pinned seams:
  1. Scheme-relative URLs (//evil.com/...) REJECTED.
  2. data:, javascript:, file:, about:, vbscript: REJECTED.
  3. Embedded credentials (user:pass@host) REJECTED.
  4. Path-relative URLs without leading `/` REJECTED.
  5. Host case-insensitive + trailing-dot tolerant.
  6. Query string + fragment preserved.
  7. Empty / None → None.
"""

from __future__ import annotations

from services.redirect_url import (
    ALLOWED_SCHEMES,
    DANGEROUS_SCHEMES,
    canonical_redirect,
    is_safe_redirect,
)

# ---------- Constants ----------


def test_dangerous_schemes_set():
    assert (
        frozenset(
            {
                "data",
                "javascript",
                "file",
                "about",
                "vbscript",
            }
        )
        == DANGEROUS_SCHEMES
    )


def test_allowed_schemes_set():
    """Pin: http and https ONLY. A refactor adding ftp surfaces."""
    assert frozenset({"http", "https"}) == ALLOWED_SCHEMES


# ---------- Relative URLs ----------


def test_path_absolute_relative_url_accepted():
    assert canonical_redirect("/dashboard", set()) == "/dashboard"


def test_relative_with_query():
    assert canonical_redirect("/settings/audit?since=7d", set()) == "/settings/audit?since=7d"


def test_relative_with_fragment():
    assert canonical_redirect("/page#section", set()) == "/page#section"


def test_relative_with_query_and_fragment():
    assert canonical_redirect("/page?a=1#section", set()) == "/page?a=1#section"


def test_path_relative_url_rejected():
    """Cardinal pin: bare `dashboard` (no leading /) REJECTED.
    Path-relative URLs are ambiguous — defends against
    misinterpretation."""
    assert canonical_redirect("dashboard", set()) is None
    assert canonical_redirect("relative-path", set()) is None


def test_root_path_accepted():
    assert canonical_redirect("/", set()) == "/"


# ---------- Scheme-relative ----------


def test_scheme_relative_rejected():
    """Cardinal pin: `//evil.com/path` REJECTED. This is the
    classic open-redirect bypass technique — pin so a refactor
    that treats `//` as relative-path slips here."""
    assert canonical_redirect("//evil.com/path", {"example.com"}) is None
    assert canonical_redirect("//example.com/path", {"example.com"}) is None


# ---------- Dangerous schemes ----------


def test_javascript_rejected():
    assert canonical_redirect("javascript:alert(1)", set()) is None


def test_data_rejected():
    """data: can be used to exfiltrate or render arbitrary HTML."""
    assert canonical_redirect("data:text/html,<script>x</script>", set()) is None


def test_file_rejected():
    """file: can read local filesystem in some contexts."""
    assert canonical_redirect("file:///etc/passwd", set()) is None


def test_about_rejected():
    assert canonical_redirect("about:blank", set()) is None


def test_vbscript_rejected():
    assert canonical_redirect("vbscript:msgbox(1)", set()) is None


def test_dangerous_scheme_case_insensitive():
    """Pin: case-insensitive scheme check. `JAVASCRIPT:` also
    rejected."""
    assert canonical_redirect("JAVASCRIPT:alert(1)", set()) is None
    assert canonical_redirect("Data:foo", set()) is None


# ---------- Unknown schemes ----------


def test_unknown_scheme_rejected():
    """Schemes not in ALLOWED_SCHEMES rejected (even if not
    explicitly dangerous)."""
    assert canonical_redirect("ftp://example.com/", {"example.com"}) is None
    assert canonical_redirect("ssh://example.com/", {"example.com"}) is None


# ---------- Allowed hosts ----------


def test_absolute_url_allowed_host_accepted():
    assert canonical_redirect("https://example.com/path", {"example.com"}) == "https://example.com/path"


def test_absolute_url_disallowed_host_rejected():
    assert canonical_redirect("https://evil.com/path", {"example.com"}) is None


def test_empty_allowed_hosts_only_relative():
    """With no allowed_hosts, only relative URLs work."""
    assert canonical_redirect("https://example.com/path", set()) is None
    assert canonical_redirect("/path", set()) == "/path"


def test_host_case_insensitive():
    """Pin: case-insensitive host comparison."""
    assert canonical_redirect("https://EXAMPLE.com/path", {"example.com"}) == "https://EXAMPLE.com/path"
    assert canonical_redirect("https://example.com/path", {"EXAMPLE.com"}) == "https://example.com/path"


def test_trailing_dot_tolerated():
    """Pin: `example.com.` (with trailing dot — DNS-canonical)
    matches `example.com`."""
    assert canonical_redirect("https://example.com./path", {"example.com"}) is not None
    assert canonical_redirect("https://example.com/path", {"example.com."}) is not None


# ---------- Embedded credentials ----------


def test_credentials_rejected():
    """Cardinal pin: `user:pass@host` REJECTED. URLs with
    embedded creds are rare but a security smell — pin against
    accidental acceptance."""
    assert (
        canonical_redirect(
            "http://user:pass@example.com/",
            {"example.com"},
        )
        is None
    )


def test_username_only_rejected():
    assert (
        canonical_redirect(
            "http://user@example.com/",
            {"example.com"},
        )
        is None
    )


# ---------- Query / fragment preservation ----------


def test_query_preserved_in_absolute():
    assert canonical_redirect("https://example.com/path?a=1", {"example.com"}) == "https://example.com/path?a=1"


def test_fragment_preserved_in_absolute():
    assert canonical_redirect("https://example.com/path#frag", {"example.com"}) == "https://example.com/path#frag"


# ---------- Defensive ----------


def test_none_returns_none():
    assert canonical_redirect(None, set()) is None


def test_empty_returns_none():
    assert canonical_redirect("", set()) is None
    assert canonical_redirect("   ", set()) is None


# ---------- is_safe_redirect ----------


def test_is_safe_relative():
    assert is_safe_redirect("/path", set()) is True


def test_is_safe_absolute_allowed():
    assert is_safe_redirect("https://example.com/", {"example.com"}) is True


def test_is_safe_javascript():
    assert is_safe_redirect("javascript:alert(1)", set()) is False


def test_is_safe_scheme_relative():
    assert is_safe_redirect("//evil.com/", {"example.com"}) is False
