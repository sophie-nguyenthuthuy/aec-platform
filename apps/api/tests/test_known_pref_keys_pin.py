"""Pin the exact tuple of `_KNOWN_PREF_KEYS` in `routers.notifications`.

Why this exists: the dashboard's notifications-prefs UI pre-fills
every key in `_KNOWN_PREF_KEYS` with default-off rows so the user
sees every available switch before their first opt-in. A regression
that:

  * **Adds** a key without registering a consumer → user sees a
    switch with no underlying delivery path.
  * **Removes** a key while users have rows for it → those rows
    disappear from the UI but still gate cron deliveries; users
    can't toggle them back on without raw SQL.
  * **Renames** a key → existing user rows for the old name silently
    stop influencing delivery; everyone's preferences are reset.

The set is small (3-4 entries) but its correctness has out-sized
customer impact — every notification preference flows through it.

If you intentionally change the set, update `EXPECTED` below in
the same PR. The two-way diff in the failure message will name
exactly which keys are off.
"""

from __future__ import annotations

from routers.notifications import _KNOWN_PREF_KEYS

# Source of truth, pinned 2026-05-04. Each entry maps to a specific
# delivery path; the comments below name the consumer that reads it
# so a reviewer can verify "added a key + added a consumer" lined up.
EXPECTED: tuple[str, ...] = (
    # Read by `services.ops_alerts._resolve_drift_recipients` to
    # gate the cross-tenant scraper-drift alert email.
    "scraper_drift",
    # Read by the (future) RFQ-deadline-summary cron. Today the
    # cron isn't wired to read this key, but the switch exists so
    # users can opt out preemptively before the cron lands.
    "rfq_deadline_summary",
    # Read by the (future) weekly-report-cron's notification path.
    # Today the cron emails everyone with a project_watch unconditionally;
    # the switch is reserved for when the cron starts gating.
    "weekly_digest_email",
)


def test_known_pref_keys_matches_expected_tuple_exactly():
    """Hard equality on the tuple. Order matters here — the dashboard
    renders switches in `_KNOWN_PREF_KEYS` order, so a reorder would
    visually shuffle the prefs page even if the set semantics stay
    intact. Pinning the tuple (not just the set) catches that.
    """
    assert _KNOWN_PREF_KEYS == EXPECTED, (
        f"_KNOWN_PREF_KEYS drifted from the pinned tuple.\n"
        f"  expected: {EXPECTED}\n"
        f"  actual:   {_KNOWN_PREF_KEYS}\n"
        f"If this is intentional, update EXPECTED in the same PR."
    )


def test_known_pref_keys_has_no_duplicates():
    """A duplicate would cause the pre-fill loop in
    `routers.notifications.list_preferences` to emit two synthetic
    rows for the same key, double-rendering the switch. Catch it
    explicitly even though the equality test above would also surface
    it — the dedicated check makes failure messages actionable.
    """
    assert len(_KNOWN_PREF_KEYS) == len(set(_KNOWN_PREF_KEYS)), (
        f"_KNOWN_PREF_KEYS has duplicate entries: "
        f"{sorted(k for k in _KNOWN_PREF_KEYS if list(_KNOWN_PREF_KEYS).count(k) > 1)}"
    )


def test_known_pref_keys_are_snake_case_strings():
    """Convention: keys are lowercase snake_case. The dashboard's
    i18n bundles look up labels by key (`alerts.<key>.title`) — a
    typo to camelCase would land in a missing-translation warning,
    not a crash, so the regression is silent at runtime. Pin the
    convention here as a tripwire.
    """
    for key in _KNOWN_PREF_KEYS:
        assert isinstance(key, str), f"non-string in _KNOWN_PREF_KEYS: {key!r}"
        assert key == key.lower(), (
            f"_KNOWN_PREF_KEYS entry {key!r} should be lowercase. i18n labels are looked up by exact key match."
        )
        assert " " not in key, f"_KNOWN_PREF_KEYS entry {key!r} contains whitespace — use snake_case instead."
        # Reject `XX...XX` mangling that's appeared in past
        # upstream-revert events on sibling closed sets.
        assert not key.startswith("XX"), f"_KNOWN_PREF_KEYS entry {key!r} looks mangled (`XX...` prefix)."
