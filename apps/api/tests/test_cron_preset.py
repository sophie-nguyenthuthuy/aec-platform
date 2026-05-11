"""Cron expression preset parser (cycle HH1).

Pinned seams:
  1. PRESETS map closed, with @midnight = @daily, @annually = @yearly.
  2. @hourly = "0 * * * *" (minute 0, NOT every minute).
  3. expand_preset returns None for unknown @-prefixed input.
  4. expand_preset passes non-@-prefixed cron expressions through.
  5. PRESET_LABELS_VI and PRESET_LABELS_EN have the same key set.
  6. humanize_cron defaults to vi locale.
  7. humanize_cron falls back to raw expression for non-presets.
"""

from __future__ import annotations

from services.cron_preset import (
    PRESET_LABELS_EN,
    PRESET_LABELS_VI,
    PRESETS,
    expand_preset,
    humanize_cron,
    is_known_preset,
)

# ---------- PRESETS ----------


def test_presets_canonical_mappings():
    """Pin each preset → expression mapping."""
    assert PRESETS["@every_minute"] == "* * * * *"
    assert PRESETS["@hourly"] == "0 * * * *"
    assert PRESETS["@daily"] == "0 0 * * *"
    assert PRESETS["@weekly"] == "0 0 * * 0"
    assert PRESETS["@monthly"] == "0 0 1 * *"
    assert PRESETS["@yearly"] == "0 0 1 1 *"


def test_hourly_is_minute_zero_not_every_minute():
    """Cardinal pin: @hourly fires at MINUTE 0 of every hour, not
    every minute. A refactor that uses `* */1 * * *` (functionally
    different — fires every minute) would silently flood the cron
    runner."""
    assert PRESETS["@hourly"] == "0 * * * *"
    assert PRESETS["@hourly"] != "* * * * *"


def test_midnight_is_alias_for_daily():
    """Per Vixie cron convention. Pin so a refactor that defines
    @midnight differently (e.g. `0 0 0 * *`) surfaces here."""
    assert PRESETS["@midnight"] == PRESETS["@daily"]


def test_annually_is_alias_for_yearly():
    assert PRESETS["@annually"] == PRESETS["@yearly"]


def test_weekly_fires_sunday_midnight():
    """0 = Sunday in Vixie cron weekday format."""
    assert PRESETS["@weekly"] == "0 0 * * 0"


# ---------- expand_preset ----------


def test_expand_known_preset():
    assert expand_preset("@hourly") == "0 * * * *"
    assert expand_preset("@daily") == "0 0 * * *"


def test_expand_alias_preset():
    """@midnight and @daily expand identically."""
    assert expand_preset("@midnight") == expand_preset("@daily")
    assert expand_preset("@annually") == expand_preset("@yearly")


def test_expand_unknown_at_prefixed_returns_none():
    """Pin: typo'd `@whatver` → None. A refactor that returns
    the raw `@whatver` would let an invalid expression slip into
    the cron runner."""
    assert expand_preset("@whatever") is None
    assert expand_preset("@hourli") is None  # typo
    assert expand_preset("@") is None


def test_expand_non_at_prefixed_passes_through():
    """Already a cron expression — pass through unchanged."""
    assert expand_preset("0 * * * *") == "0 * * * *"
    assert expand_preset("*/5 * * * *") == "*/5 * * * *"
    assert expand_preset("0 9-17 * * 1-5") == "0 9-17 * * 1-5"


def test_expand_strips_whitespace():
    assert expand_preset("  @hourly  ") == "0 * * * *"
    assert expand_preset("\t@daily\n") == "0 0 * * *"


def test_expand_none_and_empty():
    assert expand_preset(None) is None
    assert expand_preset("") is None
    assert expand_preset("   ") is None


# ---------- is_known_preset ----------


def test_is_known_preset_true_for_each_member():
    for preset in PRESETS:
        assert is_known_preset(preset) is True, f"{preset} should be known"


def test_is_known_preset_false_for_unknown():
    assert is_known_preset("@unknown") is False
    assert is_known_preset("@hourli") is False


def test_is_known_preset_false_for_cron_expression():
    """A 5-field cron expression is NOT a preset."""
    assert is_known_preset("0 * * * *") is False
    assert is_known_preset("* * * * *") is False


def test_is_known_preset_false_for_none():
    assert is_known_preset(None) is False
    assert is_known_preset("") is False


# ---------- humanize_cron ----------


def test_humanize_default_locale_is_vi():
    """Vi-VN-first per project convention."""
    assert humanize_cron("@hourly") == "Mỗi giờ"


def test_humanize_explicit_vi():
    assert humanize_cron("@hourly", "vi") == "Mỗi giờ"
    assert humanize_cron("@daily", "vi") == "Hàng ngày lúc 0:00"


def test_humanize_explicit_en():
    assert humanize_cron("@hourly", "en") == "Every hour"
    assert humanize_cron("@daily", "en") == "Daily at midnight"


def test_humanize_alias_resolves_to_same_label():
    """@midnight and @daily render the same label since they
    expand identically."""
    assert humanize_cron("@midnight", "vi") == humanize_cron("@daily", "vi")


def test_humanize_falls_back_to_raw_for_non_preset():
    """Non-preset cron expression → returned verbatim. A future
    enhancement might add natural-language formatting; pin so
    the fallback behaviour stays stable until then."""
    assert humanize_cron("0 */5 * * *") == "0 */5 * * *"
    assert humanize_cron("0 9-17 * * 1-5") == "0 9-17 * * 1-5"


def test_humanize_strips_whitespace():
    assert humanize_cron("  @hourly  ", "en") == "Every hour"


def test_humanize_none_returns_empty():
    """Chained-render-friendly: caller can do
    `humanize_cron(row.schedule)` without a None check."""
    assert humanize_cron(None) == ""
    assert humanize_cron("") == ""
    assert humanize_cron("   ") == ""


# ---------- Label map invariants ----------


def test_preset_labels_vi_covers_every_preset():
    assert frozenset(PRESET_LABELS_VI.keys()) == frozenset(PRESETS.keys())


def test_preset_labels_en_covers_every_preset():
    assert frozenset(PRESET_LABELS_EN.keys()) == frozenset(PRESETS.keys())


def test_preset_labels_vi_and_en_have_same_keys():
    """Pin so a refactor that adds a preset to one locale without
    the other surfaces here."""
    assert frozenset(PRESET_LABELS_VI.keys()) == frozenset(PRESET_LABELS_EN.keys())
