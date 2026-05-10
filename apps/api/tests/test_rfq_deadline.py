"""RFQ deadline calculator (cycle GG1).

Pinned seams:
  1. DEFAULT_DEADLINE_BUSINESS_DAYS = 5.
  2. MIN = 1, MAX = 30.
  3. override=None → DEFAULT (NOT MIN).
  4. override below MIN clamps UP; above MAX clamps DOWN.
  5. compute_deadline composes with DD2 (skips weekends + holidays).
  6. is_overdue boundary: deadline == now is NOT overdue (strict >).
  7. business_days_remaining negative when overdue.
"""

from __future__ import annotations

from datetime import date

from services.rfq_deadline import (
    DEFAULT_DEADLINE_BUSINESS_DAYS,
    MAX_DEADLINE_BUSINESS_DAYS,
    MIN_DEADLINE_BUSINESS_DAYS,
    business_days_remaining,
    compute_deadline,
    effective_business_days,
    is_overdue,
)

# Pinned reference dates (verified weekday).
MON_2026_05_11 = date(2026, 5, 11)
TUE_2026_05_12 = date(2026, 5, 12)
THU_2026_05_14 = date(2026, 5, 14)
FRI_2026_05_15 = date(2026, 5, 15)
SAT_2026_05_16 = date(2026, 5, 16)
MON_2026_05_18 = date(2026, 5, 18)


# ---------- Constants ----------


def test_default_business_days_is_five():
    """One business week. Pin so a refactor that drops to e.g.
    3 days silently shortens every untouched org's procurement
    timeline."""
    assert DEFAULT_DEADLINE_BUSINESS_DAYS == 5


def test_min_business_days_is_one():
    assert MIN_DEADLINE_BUSINESS_DAYS == 1


def test_max_business_days_is_thirty():
    """30 business days ≈ 6 calendar weeks. Pin so a bump
    surfaces in review — past 30 days is a different procurement
    process (long-tender)."""
    assert MAX_DEADLINE_BUSINESS_DAYS == 30


def test_band_ordering():
    assert MIN_DEADLINE_BUSINESS_DAYS < DEFAULT_DEADLINE_BUSINESS_DAYS
    assert DEFAULT_DEADLINE_BUSINESS_DAYS < MAX_DEADLINE_BUSINESS_DAYS


# ---------- effective_business_days ----------


def test_effective_none_override_returns_default():
    """Cardinal pin: absent override falls back to DEFAULT, NOT
    MIN. Defends against the "absent override means minimum
    window" misreading."""
    assert effective_business_days(None) == DEFAULT_DEADLINE_BUSINESS_DAYS


def test_effective_in_band_override_returned_verbatim():
    assert effective_business_days(7) == 7
    assert effective_business_days(15) == 15


def test_effective_zero_clamps_to_min():
    """Pin: `0` typo doesn't yield a same-day deadline."""
    assert effective_business_days(0) == MIN_DEADLINE_BUSINESS_DAYS


def test_effective_negative_clamps_to_min():
    assert effective_business_days(-5) == MIN_DEADLINE_BUSINESS_DAYS


def test_effective_above_max_clamps_to_max():
    assert effective_business_days(100) == MAX_DEADLINE_BUSINESS_DAYS


def test_effective_at_min_boundary():
    assert effective_business_days(1) == MIN_DEADLINE_BUSINESS_DAYS


def test_effective_at_max_boundary():
    assert effective_business_days(30) == MAX_DEADLINE_BUSINESS_DAYS


# ---------- compute_deadline ----------


def test_compute_deadline_default_is_one_business_week():
    """Mon + 5 business days = next Mon (skips Sat/Sun)."""
    assert compute_deadline(MON_2026_05_11, None) == MON_2026_05_18


def test_compute_deadline_one_business_day():
    """Mon + 1 = Tue."""
    assert compute_deadline(MON_2026_05_11, 1) == TUE_2026_05_12


def test_compute_deadline_uses_clamped_override():
    """A misconfigured `0` override should compose with the
    clamped MIN=1 — pin so the deadline is +1 business day, NOT
    same day."""
    assert compute_deadline(MON_2026_05_11, 0) == TUE_2026_05_12


def test_compute_deadline_skips_weekends():
    """Fri + 1 = next Mon (skips Sat/Sun)."""
    assert compute_deadline(FRI_2026_05_15, 1) == MON_2026_05_18


def test_compute_deadline_skips_vn_holiday():
    """Apr 29 (Wed) + 1 = May 4 (Mon next, skipping 4/30 + 5/1
    holidays + weekend). Pin DD2 composition."""
    wed = date(2026, 4, 29)
    assert compute_deadline(wed, 1) == date(2026, 5, 4)


# ---------- is_overdue ----------


def test_is_overdue_false_for_future_deadline():
    assert is_overdue(FRI_2026_05_15, MON_2026_05_11) is False


def test_is_overdue_false_at_exact_deadline():
    """Cardinal boundary pin: deadline AT now is NOT overdue.
    Strict `>` not `>=`. The RFQ has until end-of-deadline-day
    to respond."""
    assert is_overdue(FRI_2026_05_15, FRI_2026_05_15) is False


def test_is_overdue_true_one_day_past():
    assert is_overdue(FRI_2026_05_15, SAT_2026_05_16) is True


def test_is_overdue_true_far_past():
    assert is_overdue(FRI_2026_05_15, MON_2026_05_18) is True


# ---------- business_days_remaining ----------


def test_remaining_positive_for_future_deadline():
    """Mon → Fri half-open = 4 business days (Mon, Tue, Wed, Thu).
    The deadline day (Fri) is excluded from the count — pin DD2
    half-open semantics."""
    assert business_days_remaining(FRI_2026_05_15, MON_2026_05_11) == 4


def test_remaining_zero_at_exact_deadline():
    """Deadline IS today — not overdue, not remaining."""
    assert business_days_remaining(FRI_2026_05_15, FRI_2026_05_15) == 0


def test_remaining_negative_when_overdue():
    """Fri-deadline, Mon-next-now: Friday counted as 1 business
    day overdue (weekend ignored). Pin sign convention."""
    assert business_days_remaining(FRI_2026_05_15, MON_2026_05_18) == -1


def test_remaining_negative_skips_weekends():
    """Sat-overdue same as Mon-overdue — weekends don't count
    toward overdue days. Both yield -1: half-open [Fri, end)
    counts only Fri as a business day; the negation gives the
    sign-correct overdue count."""
    sat_overdue = business_days_remaining(FRI_2026_05_15, SAT_2026_05_16)
    mon_overdue = business_days_remaining(FRI_2026_05_15, MON_2026_05_18)
    assert sat_overdue == -1
    assert mon_overdue == -1


def test_remaining_at_thursday_one_day_before_deadline():
    """Thu before Fri-deadline: 1 business day remaining."""
    assert business_days_remaining(FRI_2026_05_15, THU_2026_05_14) == 1


# ---------- Composition with EE1-style clamping ----------


def test_compute_deadline_with_above_max_override():
    """Override=100 clamps to 30, which is then 30 business days."""
    issued = MON_2026_05_11
    deadline_at_max = compute_deadline(issued, MAX_DEADLINE_BUSINESS_DAYS)
    deadline_at_100 = compute_deadline(issued, 100)
    assert deadline_at_100 == deadline_at_max
