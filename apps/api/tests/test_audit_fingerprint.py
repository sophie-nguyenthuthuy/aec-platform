"""Audit row fingerprint generator (cycle RR3).

Pinned seams:
  1. Same input → same fingerprint.
  2. org_id REQUIRED (cross-tenant guard).
  3. Output 64-char lowercase hex.
  4. PAYLOAD_HASH_TRUNCATE_CHARS shared with QQ1.
  5. Composes with X1 audit_diff.
  6. Composes with QQ1 (truncate constant alignment).
"""

from __future__ import annotations

import hashlib

import pytest

from services.audit_diff import summarize_diff
from services.audit_fingerprint import fingerprint
from services.webhook_dedup_key import PAYLOAD_HASH_TRUNCATE_CHARS

# ---------- Determinism ----------


def test_same_input_same_fingerprint():
    a = fingerprint("org-1", "user@x.com", "create", "res-42", "abc1234567890123extra")
    b = fingerprint("org-1", "user@x.com", "create", "res-42", "abc1234567890123extra")
    assert a == b


def test_repeat_calls_stable():
    keys = {fingerprint("org-1", "u", "ev", "r", "h1234567890123456") for _ in range(50)}
    assert len(keys) == 1


# ---------- Output format ----------


def test_output_64_char_hex():
    fp = fingerprint("org-1", "u", "ev", "r", "h1234567890123456")
    assert len(fp) == 64
    assert all(c in "0123456789abcdef" for c in fp)


def test_output_lowercase():
    fp = fingerprint("org-1", "u", "ev", "r", "h")
    assert fp == fp.lower()


# ---------- Variance ----------


def test_different_org_different_fingerprint():
    """Cardinal cross-tenant guard."""
    a = fingerprint("org-1", "u", "ev", "r", "h1234567890123456")
    b = fingerprint("org-2", "u", "ev", "r", "h1234567890123456")
    assert a != b


def test_different_actor_different():
    a = fingerprint("org-1", "alice@x.com", "ev", "r", "h1234567890123456")
    b = fingerprint("org-1", "bob@x.com", "ev", "r", "h1234567890123456")
    assert a != b


def test_different_action_different():
    a = fingerprint("org-1", "u", "create", "r", "h1234567890123456")
    b = fingerprint("org-1", "u", "delete", "r", "h1234567890123456")
    assert a != b


def test_different_resource_different():
    a = fingerprint("org-1", "u", "ev", "res-1", "h1234567890123456")
    b = fingerprint("org-1", "u", "ev", "res-2", "h1234567890123456")
    assert a != b


def test_different_diff_first_16_different():
    a = fingerprint("org-1", "u", "ev", "r", "abcdef0123456789")
    b = fingerprint("org-1", "u", "ev", "r", "abcdef012345678X")
    assert a != b


# ---------- Truncation ----------


def test_diff_hash_beyond_16_ignored():
    """Pin: same first-16-chars → same fingerprint (matches
    QQ1's truncation behavior)."""
    a = fingerprint("org-1", "u", "ev", "r", "abcdef0123456789EXTRA1")
    b = fingerprint("org-1", "u", "ev", "r", "abcdef0123456789EXTRA2")
    assert a == b


def test_truncate_constant_matches_qq1():
    """Cross-cycle pin: this module REUSES QQ1's constant. A
    refactor that diverges would create dedup-class entropy
    inconsistency between webhook deliveries and audit rows."""
    assert PAYLOAD_HASH_TRUNCATE_CHARS == 16


def test_empty_diff_hash_works():
    """Audit rows with no payload diff still get a fingerprint."""
    fp = fingerprint("org-1", "u", "ev", "r", "")
    assert len(fp) == 64


# ---------- Required org_id ----------


def test_empty_org_id_raises():
    """Cardinal pin: org_id REQUIRED. Cross-tenant fingerprint
    collision is a security risk."""
    with pytest.raises(ValueError):
        fingerprint("", "u", "ev", "r", "h1234567890123456")


def test_other_fields_can_be_empty():
    """Other fields all allowed empty (rare audit shapes)."""
    fp = fingerprint("org-1", "", "", "", "")
    assert len(fp) == 64


# ---------- Composition with X1 ----------


def test_composes_with_x1_audit_diff():
    """Cardinal cross-cycle pin: caller hashes the X1 diff text
    and passes the hash. The fingerprint composition matches the
    X1 → SHA-256 → fingerprint pattern."""
    diff = summarize_diff({"qty": 10}, {"qty": 20})
    diff_hash = hashlib.sha256(diff.text.encode("utf-8")).hexdigest()

    fp = fingerprint(
        org_id="org-1",
        actor_id="user@example.com",
        action="estimate.update",
        resource_id="est-42",
        payload_diff_hash=diff_hash,
    )
    assert len(fp) == 64


def test_x1_diff_change_changes_fingerprint():
    """A different diff yields a different fingerprint."""
    diff_a = summarize_diff({"qty": 10}, {"qty": 20})
    diff_b = summarize_diff({"qty": 10}, {"qty": 30})
    hash_a = hashlib.sha256(diff_a.text.encode("utf-8")).hexdigest()
    hash_b = hashlib.sha256(diff_b.text.encode("utf-8")).hexdigest()

    fp_a = fingerprint("org", "u", "ev", "r", hash_a)
    fp_b = fingerprint("org", "u", "ev", "r", hash_b)
    assert fp_a != fp_b


def test_x1_identical_diff_produces_identical_fingerprint():
    """Identical diffs produce identical hashes → identical
    fingerprints. This is the dedup primitive."""
    diff_a = summarize_diff({"qty": 10}, {"qty": 20})
    diff_b = summarize_diff({"qty": 10}, {"qty": 20})
    hash_a = hashlib.sha256(diff_a.text.encode("utf-8")).hexdigest()
    hash_b = hashlib.sha256(diff_b.text.encode("utf-8")).hexdigest()

    fp_a = fingerprint("org", "u", "ev", "r", hash_a)
    fp_b = fingerprint("org", "u", "ev", "r", hash_b)
    assert fp_a == fp_b
