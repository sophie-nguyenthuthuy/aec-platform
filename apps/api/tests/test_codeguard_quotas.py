"""Tests for `services.codeguard_quotas` and route-level 429 enforcement.

The quota helpers (`check_org_quota`, `record_org_usage`) are tested
against a stubbed AsyncSession so we don't need a live Postgres for
Tier 2. The route-level enforcement test confirms that an over-quota
org gets a structured 429 from the codeguard endpoints — the load-
bearing user-visible behaviour.

The integration test for the actual SQL (UPSERT semantics, `date_trunc`
behaviour) lives in Tier 3 and runs against the service-container DB
in CI; it's the equivalent of how other modules split helper logic
(unit-tested with mocks) from SQL semantics (integration-tested with
the real DB).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

pytestmark = pytest.mark.asyncio


# ---------- check_org_quota ------------------------------------------------


class _RowStub:
    """Mimics `Row` so `.first()` returns something with attribute access."""

    def __init__(self, **fields):
        for k, v in fields.items():
            setattr(self, k, v)


def _execute_returning_first(row):
    """Build an AsyncMock for `db.execute` that returns a Result whose
    `.first()` gives back the supplied row stub. Mirrors how
    SQLAlchemy's async path actually shapes results."""
    result = MagicMock()
    result.first.return_value = row
    return AsyncMock(return_value=result)


async def test_check_quota_returns_unlimited_when_no_quota_row():
    """The opt-in enforcement contract: orgs without an explicit quota
    row are not blocked. Pin so the rollout doesn't accidentally start
    rejecting unrelated tenants."""
    from services.codeguard_quotas import check_org_quota

    db = MagicMock()
    db.execute = _execute_returning_first(None)  # no row → unlimited

    result = await check_org_quota(db, uuid4())
    assert result.over_limit is False
    assert result.limit_kind == "unlimited"
    assert result.limit is None


async def test_check_quota_under_limit_passes():
    """Quota row exists, usage is below the limit on both dimensions →
    `over_limit=False`."""
    from services.codeguard_quotas import check_org_quota

    db = MagicMock()
    db.execute = _execute_returning_first(
        _RowStub(
            monthly_input_token_limit=1_000_000,
            monthly_output_token_limit=200_000,
            input_used=300_000,
            output_used=50_000,
        )
    )

    result = await check_org_quota(db, uuid4())
    assert result.over_limit is False
    assert result.limit_kind == "unlimited"


async def test_check_quota_blocks_when_input_limit_crossed():
    """The binding dimension surfaces in `limit_kind` so the 429
    message can point at the right cap. Input crossed first."""
    from services.codeguard_quotas import check_org_quota

    db = MagicMock()
    db.execute = _execute_returning_first(
        _RowStub(
            monthly_input_token_limit=1_000_000,
            monthly_output_token_limit=200_000,
            input_used=1_000_000,  # at the limit
            output_used=50_000,
        )
    )

    result = await check_org_quota(db, uuid4())
    assert result.over_limit is True
    assert result.limit_kind == "input"
    assert result.used == 1_000_000
    assert result.limit == 1_000_000


async def test_check_quota_blocks_when_output_limit_crossed():
    """Output limit alone is enough to block — orgs typically pin on
    output (Anthropic prices output ~5× input). Pin both code paths."""
    from services.codeguard_quotas import check_org_quota

    db = MagicMock()
    db.execute = _execute_returning_first(
        _RowStub(
            monthly_input_token_limit=10_000_000,  # nowhere near
            monthly_output_token_limit=200_000,
            input_used=500_000,
            output_used=210_000,  # over
        )
    )

    result = await check_org_quota(db, uuid4())
    assert result.over_limit is True
    assert result.limit_kind == "output"
    assert result.used == 210_000


async def test_check_quota_handles_null_limit_per_dimension():
    """A quota row with NULL on one dimension means "unlimited on that
    dimension." Org pins only on the dimension that has a number."""
    from services.codeguard_quotas import check_org_quota

    db = MagicMock()
    db.execute = _execute_returning_first(
        _RowStub(
            monthly_input_token_limit=None,  # unlimited input
            monthly_output_token_limit=200_000,
            input_used=999_999_999,  # huge but no cap
            output_used=50_000,
        )
    )

    result = await check_org_quota(db, uuid4())
    assert result.over_limit is False
    assert result.limit_kind == "unlimited"


async def test_check_quota_handles_quota_with_no_usage_row():
    """Org has a quota assigned but never spent any tokens — the LEFT
    JOIN gives 0 used, not an error. First-use case for newly-created
    orgs."""
    from services.codeguard_quotas import check_org_quota

    db = MagicMock()
    db.execute = _execute_returning_first(
        _RowStub(
            monthly_input_token_limit=1_000_000,
            monthly_output_token_limit=200_000,
            input_used=0,  # COALESCE handled this in SQL
            output_used=0,
        )
    )

    result = await check_org_quota(db, uuid4())
    assert result.over_limit is False


# ---------- record_org_usage -----------------------------------------------


async def test_record_usage_skips_db_write_when_zero_tokens():
    """A request that consumed nothing (e.g. pure HyDE cache hit, or
    an early-aborted call) skips the DB hit entirely. Verified by
    asserting `db.execute` is NOT called — the no-op guard is what
    keeps free-cache requests truly free of DB load."""
    from services.codeguard_quotas import record_org_usage

    db = MagicMock()
    db.execute = AsyncMock()

    await record_org_usage(db, uuid4(), input_tokens=0, output_tokens=0)
    db.execute.assert_not_called()


async def test_record_usage_calls_db_when_tokens_present():
    """Non-zero tokens → exactly one DB execute (the UPSERT). The
    actual SQL semantics (ON CONFLICT, date_trunc) are validated by
    the Tier 3 integration test against a real Postgres."""
    from services.codeguard_quotas import record_org_usage

    db = MagicMock()
    db.execute = AsyncMock()

    org_id = uuid4()
    await record_org_usage(db, org_id, input_tokens=500, output_tokens=100)
    assert db.execute.call_count == 1
    # Inspect the parameters bound to the UPSERT — pin the param shape
    # so a future refactor of the SQL doesn't accidentally swap
    # input/output token assignment.
    args, _ = db.execute.call_args
    params = args[1]
    assert params["org_id"] == str(org_id)
    assert params["in_tok"] == 500
    assert params["out_tok"] == 100


# ---------- Threshold notifications ----------------------------------------
#
# `check_and_notify_thresholds` is the post-`record_org_usage` hook
# that emails the org's quota_warn opt-in list when usage crosses 80%
# or 95%. Pinned contracts:
#   1. First crossing → email; second crossing same period → silent.
#   2. New period (next month) → email fires again.
#   3. Recipients pulled from notification_preferences with
#      key='quota_warn' AND email_enabled=true.
#   4. The dedupe row lands EVEN when the mailer fails — a flapping
#      SMTP outage must not multi-send to the same inbox once recovered.


def _execute_returning(*results):
    """Build an `AsyncMock` for `db.execute` that returns successive
    results from `results`. Mirrors the helper used elsewhere in this
    file for SQL-shape mocking — each entry can be a `_RowStub`,
    a list, or None."""

    queue = list(results)

    async def _exec(*_a, **_kw):
        nxt = queue.pop(0) if queue else None
        result = MagicMock()
        if isinstance(nxt, list):
            result.all.return_value = nxt
            result.first.return_value = nxt[0] if nxt else None
            result.rowcount = len(nxt)
        else:
            result.first.return_value = nxt
            result.all.return_value = [nxt] if nxt is not None else []
            # Default rowcount=1 for non-list non-None (a successful
            # INSERT/UPDATE) and 0 for None (ON CONFLICT DO NOTHING).
            result.rowcount = 0 if nxt is None else 1
        return result

    return AsyncMock(side_effect=_exec)


async def test_threshold_fires_email_when_crossing_80pct(monkeypatch):
    """Standard happy path: usage just crossed 80% on input → claim
    the dedupe row, look up recipients, send one email per recipient."""
    import datetime as _dt

    from services import codeguard_quotas as _q

    org_id = uuid4()
    db = MagicMock()
    # Execute call sequence:
    #   1. quota+usage SELECT (returns the at-85% row)
    #   2. SELECT existing dedupe rows (none yet)
    #   3. SELECT period_start (a single-column row)
    #   4. INSERT…ON CONFLICT (rowcount=1 → claimed)
    #   5. SELECT quota_warn recipients
    db.execute = _execute_returning(
        _RowStub(
            in_lim=1_000_000,
            out_lim=200_000,
            in_used=850_000,  # 85%
            out_used=10_000,  # 5%, below threshold
            period_start=_dt.date(2026, 5, 1),
        ),
        [],  # no existing dedupe rows
        _RowStub(p=_dt.date(2026, 5, 1)),  # period_start lookup
        # Bare INSERT…ON CONFLICT result — `_execute_returning` defaults
        # `rowcount=1` for a non-None first row. We pass a placeholder
        # (any non-None value) so the rowcount=1 (claimed) path fires.
        _RowStub(),
        # Recipients now carry per-channel intent. Email-only user.
        [_RowStub(email="finance@example.com", email_enabled=True, slack_enabled=False)],
    )

    sent: list[dict] = []

    async def _fake_mailer(**kwargs):
        sent.append(kwargs)
        return {"to": kwargs["to"], "delivered": True, "reason": None}

    async def _fake_slacker(**_kw):
        raise AssertionError("Slack must NOT fire for an email-only recipient")

    summaries = await _q.check_and_notify_thresholds(db, org_id, mailer=_fake_mailer, slacker=_fake_slacker)

    assert len(summaries) == 1
    assert summaries[0]["dimension"] == "input"
    assert summaries[0]["threshold"] == 80
    assert summaries[0]["recipients"] == ["finance@example.com"]
    assert summaries[0]["delivered_email"] == 1
    assert summaries[0]["delivered_slack"] == 0
    # Email actually went out — pin subject substring + recipient.
    assert len(sent) == 1
    assert sent[0]["to"] == "finance@example.com"
    assert "85.0%" in sent[0]["subject"]


async def test_threshold_fires_critical_email_at_95pct():
    """At 95%+, the email uses the "Sắp đạt" critical copy and points
    at /codeguard/quota in the body. Pin both halves so a refactor
    that mixes up the warn/critical templates is visible."""
    import datetime as _dt

    from services import codeguard_quotas as _q

    org_id = uuid4()
    db = MagicMock()
    db.execute = _execute_returning(
        _RowStub(
            in_lim=1_000_000,
            out_lim=200_000,
            in_used=200_000,  # 20%
            out_used=192_000,  # 96%
            period_start=_dt.date(2026, 5, 1),
        ),
        [],  # no dedupe rows yet
        _RowStub(p=_dt.date(2026, 5, 1)),  # period_start lookup, ONCE
        # _crossed_thresholds returns BOTH 95 AND 80 (descending) since
        # 96% has crossed both bands for the first time. The helper
        # iterates over them; each event needs claim + recipients.
        _RowStub(),  # claim 95% row
        # Email-only recipient — same shape as test above.
        [_RowStub(email="oncall@example.com", email_enabled=True, slack_enabled=False)],
        _RowStub(),  # claim 80% row
        [_RowStub(email="oncall@example.com", email_enabled=True, slack_enabled=False)],
    )

    sent: list[dict] = []

    async def _fake_mailer(**kwargs):
        sent.append(kwargs)
        return {"to": kwargs["to"], "delivered": True, "reason": None}

    summaries = await _q.check_and_notify_thresholds(db, org_id, mailer=_fake_mailer)
    # Both thresholds fire on the same call (96% crosses BOTH bands
    # for the first time). Pin the 95% one specifically.
    critical = next(s for s in summaries if s["threshold"] == 95)
    assert critical["dimension"] == "output"
    # Two emails went out — one per threshold.
    critical_email = next(e for e in sent if "Sắp đạt" in e["subject"])
    assert "96.0%" in critical_email["subject"]
    # Absolute URL — relative paths render as inert text in most email
    # clients. The link MUST be `<base>/codeguard/quota`, not a bare
    # path. Assert the host portion appears alongside the path so a
    # regression that drops the prefix is visible.
    assert "://" in critical_email["text_body"], (
        f"Expected an absolute URL in the email body, got: {critical_email['text_body']!r}. "
        "If the link starts with `/codeguard/quota`, the `_quota_page_url` helper "
        "wasn't called or `web_base_url` got dropped from the format string."
    )
    assert "/codeguard/quota" in critical_email["text_body"]
    assert "/codeguard/quota" in critical_email["html_body"]


async def test_threshold_silent_when_dedupe_row_exists():
    """Already-sent threshold for this period → no email, no claim
    insert. The whole point of the dedupe table — finance shouldn't
    get spammed every minute when the org is parked at 81%."""
    import datetime as _dt

    from services import codeguard_quotas as _q

    org_id = uuid4()
    db = MagicMock()
    # 80% on input crossed AND a dedupe row already exists for it.
    db.execute = _execute_returning(
        _RowStub(
            in_lim=1_000_000,
            out_lim=200_000,
            in_used=820_000,
            out_used=10_000,
            period_start=_dt.date(2026, 5, 1),
        ),
        # Existing dedupe row covers the (input, 80) band.
        [_RowStub(dimension="input", threshold=80)],
    )

    async def _mailer_should_never_be_called(**_kw):
        raise AssertionError("mailer must not fire when dedupe row exists")

    summaries = await _q.check_and_notify_thresholds(db, org_id, mailer=_mailer_should_never_be_called)
    assert summaries == []


async def test_threshold_silent_for_unlimited_org():
    """No quota row → unlimited org → nothing to fire. The check must
    short-circuit at the first SELECT and not even look up the dedupe
    table."""
    from services import codeguard_quotas as _q

    db = MagicMock()
    db.execute = _execute_returning(None)  # quota+usage SELECT returns nothing

    async def _mailer_should_never_be_called(**_kw):
        raise AssertionError("mailer must not fire for unlimited orgs")

    summaries = await _q.check_and_notify_thresholds(db, uuid4(), mailer=_mailer_should_never_be_called)
    assert summaries == []


async def test_threshold_silent_when_claim_loses_race():
    """Two concurrent `record_org_usage` calls both see "no dedupe
    row exists" but only ONE INSERT lands. The loser must observe
    rowcount=0 from `ON CONFLICT DO NOTHING` and skip the email.

    Without this pin, a tight burst of LLM calls all crossing 80%
    in the same second could fan out N emails to the same recipient."""
    import datetime as _dt

    from services import codeguard_quotas as _q

    db = MagicMock()
    # Quota+usage at 85%, no existing dedupe rows... but the INSERT
    # claim returns rowcount=0 (concurrent peer beat us to it).
    losing_claim = MagicMock()
    losing_claim.rowcount = 0  # peer claimed first
    losing_claim.first.return_value = None
    losing_claim.all.return_value = []

    queue = [
        _RowStub(
            in_lim=1_000_000,
            out_lim=200_000,
            in_used=850_000,
            out_used=10_000,
            period_start=_dt.date(2026, 5, 1),
        ),
        [],  # no dedupe rows yet
        _RowStub(p=_dt.date(2026, 5, 1)),  # period_start
        losing_claim,  # rowcount=0 claim path
    ]

    async def _exec(*_a, **_kw):
        nxt = queue.pop(0) if queue else None
        if hasattr(nxt, "rowcount"):
            return nxt
        result = MagicMock()
        if isinstance(nxt, list):
            result.all.return_value = nxt
            result.first.return_value = nxt[0] if nxt else None
        else:
            result.first.return_value = nxt
            result.all.return_value = [nxt] if nxt is not None else []
            result.rowcount = 0 if nxt is None else 1
        return result

    db.execute = AsyncMock(side_effect=_exec)

    async def _mailer_should_not_fire(**_kw):
        raise AssertionError("mailer must not fire when the claim was lost")

    summaries = await _q.check_and_notify_thresholds(db, uuid4(), mailer=_mailer_should_not_fire)
    assert summaries == []


async def test_threshold_records_no_recipients_summary_when_nobody_opted_in():
    """If the org has no users opted into `quota_warn`, the dedupe row
    still gets claimed (so we don't re-attempt later) but the summary
    records `recipients=[]` and `delivered=0`. Lets the caller's logs
    surface "warned but nobody listening" — useful for getting opt-in
    coverage right during rollout."""
    import datetime as _dt

    from services import codeguard_quotas as _q

    org_id = uuid4()
    db = MagicMock()
    db.execute = _execute_returning(
        _RowStub(
            in_lim=1_000_000,
            out_lim=200_000,
            in_used=850_000,
            out_used=10_000,
            period_start=_dt.date(2026, 5, 1),
        ),
        [],  # no dedupe yet
        _RowStub(p=_dt.date(2026, 5, 1)),
        _RowStub(),  # claim succeeds
        [],  # no recipients
    )

    async def _mailer_should_never_fire(**_kw):
        raise AssertionError("mailer must not fire when there are no recipients")

    summaries = await _q.check_and_notify_thresholds(db, org_id, mailer=_mailer_should_never_fire)
    assert len(summaries) == 1
    assert summaries[0]["recipients"] == []
    assert summaries[0]["delivered_email"] == 0
    assert summaries[0]["delivered_slack"] == 0


# ---------- Threshold cross-channel dispatch ------------------------------
#
# `notification_preferences` has both `email_enabled` AND `slack_enabled`
# columns — pre-this-fix only email was wired. Pin all four combinations:
#   email-only / slack-only / both / neither
# A regression that drops one channel (or fans out wrong) would silently
# under-notify the recipients that opted in to it.


async def test_threshold_slack_only_user_gets_slack_post_no_email(monkeypatch):
    """User with `slack_enabled=TRUE, email_enabled=FALSE` — must get
    a Slack post and NO email. Pin so the email channel doesn't
    accidentally become a fallback for Slack-only opt-ins."""
    import datetime as _dt

    from services import codeguard_quotas as _q

    org_id = uuid4()
    db = MagicMock()
    db.execute = _execute_returning(
        _RowStub(
            in_lim=1_000_000,
            out_lim=200_000,
            in_used=850_000,
            out_used=10_000,
            period_start=_dt.date(2026, 5, 1),
        ),
        [],
        _RowStub(p=_dt.date(2026, 5, 1)),
        _RowStub(),  # claim
        [_RowStub(email="ops@example.com", email_enabled=False, slack_enabled=True)],
    )

    slack_calls: list[dict] = []

    async def _fake_slack(**kwargs):
        slack_calls.append(kwargs)
        return {"delivered": True, "reason": None, "status": 200}

    async def _mailer_must_not_fire(**_kw):
        raise AssertionError("Email must not fire for slack-only recipient")

    summaries = await _q.check_and_notify_thresholds(db, org_id, mailer=_mailer_must_not_fire, slacker=_fake_slack)
    assert summaries[0]["delivered_email"] == 0
    assert summaries[0]["delivered_slack"] == 1
    # Recipients list excludes slack-only users (it's email-shaped for
    # backwards-compat) — pin so a refactor that conflates the two
    # views doesn't accidentally start emailing slack-only users.
    assert summaries[0]["recipients"] == []
    assert len(slack_calls) == 1
    # Block-Kit shape: text + blocks. The Slack helper renders a
    # header + section + context. Pin enough to catch a regression
    # that swaps the renderer for a plain-text fallback.
    assert "85.0%" in slack_calls[0]["text"]
    assert any(b.get("type") == "header" for b in slack_calls[0]["blocks"])


async def test_threshold_dual_channel_user_gets_both(monkeypatch):
    """User with both channels enabled gets BOTH an email and a Slack
    post. Pin so a refactor that introduces "prefer one channel"
    routing doesn't silently demote dual-opt-in to single-channel."""
    import datetime as _dt

    from services import codeguard_quotas as _q

    org_id = uuid4()
    db = MagicMock()
    db.execute = _execute_returning(
        _RowStub(
            in_lim=1_000_000,
            out_lim=200_000,
            in_used=850_000,
            out_used=10_000,
            period_start=_dt.date(2026, 5, 1),
        ),
        [],
        _RowStub(p=_dt.date(2026, 5, 1)),
        _RowStub(),
        [_RowStub(email="alice@example.com", email_enabled=True, slack_enabled=True)],
    )

    emails: list[dict] = []
    slacks: list[dict] = []

    async def _fake_mailer(**kwargs):
        emails.append(kwargs)
        return {"to": kwargs["to"], "delivered": True, "reason": None}

    async def _fake_slacker(**kwargs):
        slacks.append(kwargs)
        return {"delivered": True, "reason": None, "status": 200}

    summaries = await _q.check_and_notify_thresholds(db, org_id, mailer=_fake_mailer, slacker=_fake_slacker)
    assert summaries[0]["delivered_email"] == 1
    assert summaries[0]["delivered_slack"] == 1
    assert len(emails) == 1
    assert len(slacks) == 1
    assert summaries[0]["recipients"] == ["alice@example.com"]


async def test_threshold_slack_fires_at_most_once_per_event(monkeypatch):
    """When N opted-in users all have `slack_enabled=TRUE`, the global
    webhook is hit ONCE per event (not N times). Posting per user
    would spam the same #channel N times for the same threshold
    crossing — comically bad UX. Pin until per-user Slack DMs are
    a feature."""
    import datetime as _dt

    from services import codeguard_quotas as _q

    org_id = uuid4()
    db = MagicMock()
    db.execute = _execute_returning(
        _RowStub(
            in_lim=1_000_000,
            out_lim=200_000,
            in_used=850_000,
            out_used=10_000,
            period_start=_dt.date(2026, 5, 1),
        ),
        [],
        _RowStub(p=_dt.date(2026, 5, 1)),
        _RowStub(),
        [
            _RowStub(email="a@x.com", email_enabled=True, slack_enabled=True),
            _RowStub(email="b@x.com", email_enabled=True, slack_enabled=True),
            _RowStub(email="c@x.com", email_enabled=True, slack_enabled=True),
        ],
    )

    slacks: list[dict] = []

    async def _fake_mailer(**_kw):
        return {"delivered": True}

    async def _fake_slacker(**kwargs):
        slacks.append(kwargs)
        return {"delivered": True}

    summaries = await _q.check_and_notify_thresholds(db, org_id, mailer=_fake_mailer, slacker=_fake_slacker)
    # 3 emails, exactly 1 Slack post.
    assert summaries[0]["delivered_email"] == 3
    assert summaries[0]["delivered_slack"] == 1
    assert len(slacks) == 1


async def test_threshold_slack_failure_does_not_block_email(monkeypatch):
    """Slack webhook returns `delivered=False` (timeout, 4xx, missing
    config) — email should still fire. Cross-channel failure
    isolation: one channel down must not silently take down the
    other. Pin via a slacker that returns `delivered=False`."""
    import datetime as _dt

    from services import codeguard_quotas as _q

    org_id = uuid4()
    db = MagicMock()
    db.execute = _execute_returning(
        _RowStub(
            in_lim=1_000_000,
            out_lim=200_000,
            in_used=850_000,
            out_used=10_000,
            period_start=_dt.date(2026, 5, 1),
        ),
        [],
        _RowStub(p=_dt.date(2026, 5, 1)),
        _RowStub(),
        [_RowStub(email="finance@example.com", email_enabled=True, slack_enabled=True)],
    )

    async def _fake_mailer(**_kw):
        return {"delivered": True}

    async def _slack_down(**_kw):
        return {"delivered": False, "reason": "slack_not_configured", "status": None}

    summaries = await _q.check_and_notify_thresholds(db, org_id, mailer=_fake_mailer, slacker=_slack_down)
    # Email succeeded, Slack didn't — both reported in the summary.
    assert summaries[0]["delivered_email"] == 1
    assert summaries[0]["delivered_slack"] == 0


async def test_render_threshold_slack_critical_uses_rotating_light(monkeypatch):
    """95%+ → rotating-light emoji (matches the red banner color band).
    80% → plain warning emoji. Pin both so a refactor that flips them
    is visible — the Slack convention encodes urgency at a glance."""
    from core.config import get_settings
    from services.codeguard_quotas import _render_threshold_slack

    monkeypatch.setattr(get_settings(), "web_base_url", "https://app.example.com")

    crit_text, crit_blocks = _render_threshold_slack(
        dimension="output", threshold=95, used=192_000, limit=200_000, percent=96.0
    )
    assert ":rotating_light:" in crit_text
    # Quota URL absolute, embedded in the context block.
    ctx = next(b for b in crit_blocks if b["type"] == "context")
    assert "https://app.example.com/codeguard/quota" in ctx["elements"][0]["text"]

    warn_text, _ = _render_threshold_slack(dimension="input", threshold=80, used=850_000, limit=1_000_000, percent=85.0)
    assert ":warning:" in warn_text
    assert ":rotating_light:" not in warn_text


# ---------- Threshold-email body rendering ---------------------------------


async def test_render_threshold_email_uses_absolute_url(monkeypatch):
    """The text + HTML bodies must embed an absolute URL built from
    `Settings.web_base_url`. Most email clients (Gmail, Outlook web,
    Apple Mail) won't make a relative `/codeguard/quota` href clickable
    — without the host prefix the CTA we built becomes inert text.

    Pin via a settings override so a regression that hardcodes the
    prefix (or drops the prefix entirely) is caught here, not via a
    user complaint about a dead link.
    """
    from core.config import get_settings
    from services.codeguard_quotas import _render_threshold_email

    # Override `web_base_url` on the cached settings object. This is
    # the same shape as the override-pattern used in test_*_router.py
    # files for `email_from`, `smtp_host`, etc.
    settings = get_settings()
    monkeypatch.setattr(settings, "web_base_url", "https://app.example.com")

    subject, text_body, html_body = _render_threshold_email(
        dimension="input",
        threshold=80,
        used=850_000,
        limit=1_000_000,
        percent=85.0,
    )

    expected_url = "https://app.example.com/codeguard/quota"
    assert expected_url in text_body, f"Expected absolute URL {expected_url!r} in text body, got: {text_body!r}"
    assert f'href="{expected_url}"' in html_body, f'Expected `href="{expected_url}"` in HTML body, got: {html_body!r}'
    # Sanity: the bare relative path must NOT appear standalone in the
    # text body (else a refactor that left a dangling `/codeguard/quota`
    # alongside the absolute URL would still pass).
    bare_relative_count = text_body.count("/codeguard/quota")
    absolute_count = text_body.count(expected_url)
    assert bare_relative_count == absolute_count, (
        f"Found {bare_relative_count} `/codeguard/quota` substrings vs "
        f"{absolute_count} absolute URLs — there's a stray relative path "
        "somewhere in the body that wasn't prefixed."
    )


async def test_render_threshold_email_strips_trailing_slash_from_base():
    """`web_base_url` may legitimately have a trailing slash from env
    config (`WEB_BASE_URL=https://app.example.com/`). The helper must
    normalise so the URL doesn't render as `app.example.com//codeguard/quota`
    (some clients tolerate the double slash, others don't)."""
    from core.config import get_settings
    from services.codeguard_quotas import _quota_page_url

    settings = get_settings()
    original = settings.web_base_url
    try:
        settings.web_base_url = "https://app.example.com/"
        assert _quota_page_url() == "https://app.example.com/codeguard/quota"
        settings.web_base_url = "https://app.example.com"  # no slash
        assert _quota_page_url() == "https://app.example.com/codeguard/quota"
    finally:
        settings.web_base_url = original


async def test_render_threshold_email_critical_uses_critical_copy(monkeypatch):
    """`threshold=95` → "Sắp đạt" critical subject + "may 429" body.
    `threshold=80` → "Cảnh báo" warn subject + "reset đầu tháng" body.
    The two paths have visibly different urgency; pin both so a refactor
    that mistakenly routes 95 through the warn template (or vice versa)
    is caught."""
    from core.config import get_settings
    from services.codeguard_quotas import _render_threshold_email

    monkeypatch.setattr(get_settings(), "web_base_url", "https://x.test")

    crit_subject, crit_text, _ = _render_threshold_email(
        dimension="output",
        threshold=95,
        used=192_000,
        limit=200_000,
        percent=96.0,
    )
    assert "Sắp đạt" in crit_subject
    assert "HTTP 429" in crit_text

    warn_subject, warn_text, _ = _render_threshold_email(
        dimension="input",
        threshold=80,
        used=850_000,
        limit=1_000_000,
        percent=85.0,
    )
    assert "Đã dùng" in warn_subject
    assert "reset" in warn_text.lower()
    # Critical copy must NOT leak into the warn body.
    assert "HTTP 429" not in warn_text


# ---------- vi-VN number formatter -----------------------------------------


async def test_cap_check_ticks_429_counter_and_observes_latency(client, monkeypatch):
    """Pin the observability contract on the cap-check helper:

      * `codeguard_quota_429_total{limit_kind}` ticks once per refused
        request, labelled with the binding dimension.
      * `codeguard_quota_check_duration_seconds` records ONE observation
        per cap-check (regardless of allow/deny). Ops need this to spot
        the cap-check inflating p95 on LLM routes.

    Without these metrics, dashboards can't answer "are we capping out
    tenants more after the latest deploy" without grepping pod logs —
    which is exactly the scrap-the-fleet workflow the prometheus
    exporter exists to avoid.
    """
    from core import metrics
    from services.codeguard_quotas import QuotaCheckResult

    # Snapshot the relevant counter / histogram state BEFORE the call
    # so the assertion is robust to other tests in this file having
    # already fired the cap-check (the metrics module is process-wide
    # state). We diff before/after rather than asserting absolute counts.
    before_429 = metrics.codeguard_quota_429_total._values.get(("input",), 0.0)
    before_obs = metrics.codeguard_quota_check_duration_seconds._observations.get((), [0.0, 0.0])
    before_count = before_obs[1] if len(before_obs) >= 2 else 0.0

    async def _over_quota(_db, _org_id):
        return QuotaCheckResult(over_limit=True, limit_kind="input", used=1_500_000, limit=1_000_000)

    monkeypatch.setattr("services.codeguard_quotas.check_org_quota", _over_quota)

    res = await client.post(
        "/api/v1/codeguard/query",
        json={"question": "blocked"},
    )
    assert res.status_code == 429

    after_429 = metrics.codeguard_quota_429_total._values.get(("input",), 0.0)
    after_count = metrics.codeguard_quota_check_duration_seconds._observations.get((), [0.0, 0.0])[1]
    assert after_429 == before_429 + 1, (
        "Counter `codeguard_quota_429_total{limit_kind=input}` should have "
        f"incremented by exactly 1 (was {before_429}, now {after_429}). "
        "Did the cap-check helper stop calling `.inc()`?"
    )
    assert after_count == before_count + 1, (
        f"Histogram should have observed exactly one new sample (was "
        f"count={before_count}, now {after_count}). Either the helper "
        "stopped wrapping the SELECT or the try/finally guard regressed."
    )


async def test_cap_check_does_not_tick_429_when_under_limit(monkeypatch):
    """The histogram observation fires on every cap-check (under or
    over), but the 429 counter must ONLY tick on refused requests. A
    regression that increments the counter unconditionally would inflate
    the dashboard's "tenants getting capped" view by every successful
    request — silent but very wrong.

    Calls the helper directly rather than through a route — keeps the
    test self-contained (doesn't depend on the LLM mocking, auth, etc.)
    and pins the contract at the helper boundary where the observation
    happens.
    """
    from uuid import uuid4

    from core import metrics
    from routers.codeguard import _check_quota_or_raise
    from services.codeguard_quotas import QuotaCheckResult

    before_429_input = metrics.codeguard_quota_429_total._values.get(("input",), 0.0)
    before_429_output = metrics.codeguard_quota_429_total._values.get(("output",), 0.0)
    before_count = metrics.codeguard_quota_check_duration_seconds._observations.get((), [0.0, 0.0])[1]

    async def _under_quota(_db, _org_id):
        return QuotaCheckResult(over_limit=False, limit_kind="unlimited", used=0, limit=None)

    monkeypatch.setattr("services.codeguard_quotas.check_org_quota", _under_quota)

    # `db` is unused by the stubbed check_org_quota; passing None is
    # fine here. The point is the helper runs to completion without
    # raising, and the metric deltas reflect "observed once, no 429."
    await _check_quota_or_raise(None, uuid4())  # type: ignore[arg-type]

    after_429_input = metrics.codeguard_quota_429_total._values.get(("input",), 0.0)
    after_429_output = metrics.codeguard_quota_429_total._values.get(("output",), 0.0)
    after_count = metrics.codeguard_quota_check_duration_seconds._observations.get((), [0.0, 0.0])[1]

    # Counter unchanged on the under-limit path.
    assert after_429_input == before_429_input
    assert after_429_output == before_429_output
    # Histogram still got an observation (cap-check ran).
    assert after_count == before_count + 1


async def test_format_vi_int_uses_dot_grouping_not_comma():
    """vi-VN convention: thousands separator is `.`, decimal separator
    is `,`. The router-side helper has to match what the banner / quota
    page render so the 429 toast doesn't read jarring against the
    surrounding UI. A regression to Python's default `:,` formatting
    would silently re-introduce English-style grouping in the only
    user-facing string the cap-check produces."""
    from routers.codeguard import _format_vi_int

    assert _format_vi_int(1_500_000) == "1.500.000"
    assert _format_vi_int(0) == "0"
    assert _format_vi_int(999) == "999"
    assert _format_vi_int(1_000) == "1.000"
    # NULL limit (the unlimited-on-this-axis path that tripped over_limit
    # somehow) renders as "?" rather than crashing the format.
    assert _format_vi_int(None) == "?"


# ---------- Route enforcement: structured 429 ------------------------------


async def test_query_route_returns_429_when_org_over_quota(client, monkeypatch):
    """End-to-end: an over-quota org calling /query gets a 429 with the
    standard envelope shape. The pipeline is NOT invoked — proven by
    not setting up `mock_llm.query`, which would fail loudly if the
    route somehow reached the LLM layer."""
    from services.codeguard_quotas import QuotaCheckResult

    # Force the quota check to report over-limit. We patch at the
    # service-module level so the route's import resolves to our stub.
    async def _over_quota(_db, _org_id):
        return QuotaCheckResult(over_limit=True, limit_kind="output", used=210_000, limit=200_000)

    monkeypatch.setattr("services.codeguard_quotas.check_org_quota", _over_quota)

    # Defensive: if record_usage somehow gets called, no-op (the dep
    # raises before reaching it, but pin the contract).
    async def _noop_record(*_a, **_kw):
        return None

    monkeypatch.setattr("services.codeguard_quotas.record_org_usage", _noop_record)

    res = await client.post(
        "/api/v1/codeguard/query",
        json={"question": "Will not be answered, quota exceeded"},
    )
    assert res.status_code == 429
    body = res.json()
    assert body["errors"] is not None
    msg = body["errors"][0]["message"]
    # The dimension label ("output") is preserved as-is so it matches
    # the banner copy elsewhere in the UI ("hạn mức output"). The
    # surrounding copy is Vietnamese — pin a substring rather than the
    # whole message so a future tweak of the prefix doesn't trip this
    # unrelated assertion.
    assert "output" in msg
    assert "Đã vượt hạn mức" in msg, (
        f"Expected the Vietnamese 429 copy ('Đã vượt hạn mức ...') but got: {msg!r}. "
        "Did the message regress to the previous English string?"
    )
    # vi-VN dot grouping, NOT comma grouping. Pinning both halves
    # because a regression to `:,` formatting would silently render
    # `210,000 / 200,000` in a Vietnamese error string — visibly
    # inconsistent with the surrounding banner / quota page.
    assert "210.000" in msg
    assert "200.000" in msg
    # The 429 must surface a `details_url` pointing at the in-app quota
    # planning page — that's what lets the toast render a "Xem hạn mức"
    # CTA. Without this, the user sees the error but has no path from
    # "I hit the cap" to "where do I see my usage." Pin the exact URL
    # so a frontend regression that mis-routes can't slip in unnoticed.
    assert body["errors"][0]["details_url"] == "/codeguard/quota"


@pytest.mark.parametrize(
    "method,path,body",
    [
        # Each LLM-invoking route must apply the same quota gate. The
        # parametrise covers the five routes that were previously
        # unprotected — only `/query` had the inline check originally,
        # leaving the other five as free bypasses for over-quota orgs.
        ("post", "/api/v1/codeguard/query/stream", {"question": "blocked stream"}),
        (
            "post",
            "/api/v1/codeguard/scan",
            {
                "project_id": "11111111-1111-1111-1111-111111111111",
                "parameters": {"project_type": "residential"},
            },
        ),
        (
            "post",
            "/api/v1/codeguard/scan/stream",
            {
                "project_id": "11111111-1111-1111-1111-111111111111",
                "parameters": {"project_type": "residential"},
            },
        ),
        (
            "post",
            "/api/v1/codeguard/permit-checklist",
            {
                "project_id": "11111111-1111-1111-1111-111111111111",
                "jurisdiction": "Hồ Chí Minh",
                "project_type": "residential",
            },
        ),
        (
            "post",
            "/api/v1/codeguard/permit-checklist/stream",
            {
                "project_id": "11111111-1111-1111-1111-111111111111",
                "jurisdiction": "Hồ Chí Minh",
                "project_type": "residential",
            },
        ),
    ],
)
async def test_all_llm_routes_return_429_when_org_over_quota(client, monkeypatch, method, path, body):
    """Cross-route 429 contract: every LLM-invoking surface (six total —
    one Q&A, two scan, three checklist when counting both stream/non-stream
    variants) gates on the same quota check. A regression that drops the
    pre-flight from any of them re-opens a free bypass for over-quota
    orgs and would silently ship without this parametrised test catching it.

    The /query route has its own dedicated test above; this one covers
    the five routes that were unprotected at the start of this round."""
    from services.codeguard_quotas import QuotaCheckResult

    async def _over_quota(_db, _org_id):
        return QuotaCheckResult(over_limit=True, limit_kind="input", used=1_500_000, limit=1_000_000)

    monkeypatch.setattr("services.codeguard_quotas.check_org_quota", _over_quota)

    res = await getattr(client, method)(path, json=body)
    assert res.status_code == 429, (
        f"{method.upper()} {path} returned {res.status_code} instead of 429 "
        f"when over quota — the inline _check_quota_or_raise call is "
        "missing from this route or has been short-circuited."
    )
    body_json = res.json()
    assert body_json["errors"] is not None
    msg = body_json["errors"][0]["message"]
    assert "input" in msg
    assert "Đã vượt hạn mức" in msg
    # `details_url` must be present on every LLM-route 429, not just
    # /query. A regression that re-implemented the cap-check helper
    # for one route without copying the dict-detail shape would be
    # caught here.
    assert body_json["errors"][0]["details_url"] == "/codeguard/quota"


async def test_query_route_drains_telemetry_accumulator_into_record_org_usage(
    client, monkeypatch, mock_llm, make_query_response
):
    """The load-bearing contract for the cap-enforcement story.

    The previous wiring called `record_org_usage(in_tok=..., out_tok=...)`
    with kwarg names that didn't match the function's signature. Every
    call raised TypeError, got swallowed by the surrounding try/except,
    and silently produced a no-op. Result: the usage table never got
    written, so `check_org_quota` always saw 0 spend and the cap could
    never trip in real traffic.

    This test stubs the LLM via the `mock_llm` fixture (so no real
    Anthropic call) and stubs `set_telemetry_accumulator` to record
    a non-zero accumulator state — proving that the route's
    `_with_usage_recording` wrap actually drains accumulated tokens
    into `record_org_usage` with the correct kwarg names. A regression
    that re-introduces the kwarg mismatch would surface here as a
    TypeError in `record_org_usage` (visible because we don't swallow
    in this stub).
    """
    from services.codeguard_quotas import QuotaCheckResult

    async def _under_quota(_db, _org_id):
        return QuotaCheckResult(over_limit=False, limit_kind="unlimited", used=0, limit=None)

    monkeypatch.setattr("services.codeguard_quotas.check_org_quota", _under_quota)

    # Capture every call to record_org_usage so we can assert on the
    # final invocation. The `_with_usage_recording` helper short-circuits
    # when both counters are 0, so we need to seed the accumulator with
    # non-zero counts to prove the drain path actually fires.
    recorded: list[dict] = []

    async def _capturing_record(_db, org_id, *, input_tokens, output_tokens):
        recorded.append(
            {
                "org_id": org_id,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            }
        )

    monkeypatch.setattr("services.codeguard_quotas.record_org_usage", _capturing_record)

    # Have the pipeline's `set_telemetry_accumulator` populate the
    # accumulator with non-zero counts so the drain path is exercised.
    # We can't get the LLM mock to populate it (the mock_llm fixture
    # bypasses `_record_llm_call` entirely), so we hook into the bind
    # itself to seed the counters.
    from ml.pipelines import codeguard as cg_pipeline

    real_set = cg_pipeline.set_telemetry_accumulator

    def _set_with_seed(acc):
        # Mock LLM doesn't accumulate naturally; seed so the drain has
        # something to write. Real traffic gets these counts via
        # `_record_llm_call`'s on_llm_end path.
        if acc is not None:
            acc.input_tokens = 1234
            acc.output_tokens = 567
        return real_set(acc)

    monkeypatch.setattr(cg_pipeline, "set_telemetry_accumulator", _set_with_seed)

    mock_llm.query(returns=make_query_response())

    res = await client.post(
        "/api/v1/codeguard/query",
        json={"question": "Should record usage on the way out"},
    )
    assert res.status_code == 200, res.text

    # The drain fired exactly once with the seeded counts.
    assert len(recorded) == 1, (
        f"expected exactly one record_org_usage call, got {len(recorded)}: "
        "the route's _with_usage_recording wrap is missing or the helper "
        "isn't draining on success."
    )
    call = recorded[0]
    assert call["input_tokens"] == 1234
    assert call["output_tokens"] == 567


async def test_query_route_passes_through_when_org_under_quota(client, monkeypatch, mock_llm, make_query_response):
    """Mirror of the over-quota test: under-quota orgs flow through
    normally. Pin so a regression that misreads the QuotaCheckResult
    doesn't accidentally block under-quota requests."""
    from services.codeguard_quotas import QuotaCheckResult

    async def _under_quota(_db, _org_id):
        return QuotaCheckResult(over_limit=False, limit_kind="unlimited", used=0, limit=None)

    async def _noop_record(*_a, **_kw):
        return None

    monkeypatch.setattr("services.codeguard_quotas.check_org_quota", _under_quota)
    monkeypatch.setattr("services.codeguard_quotas.record_org_usage", _noop_record)

    mock_llm.query(returns=make_query_response())

    res = await client.post(
        "/api/v1/codeguard/query",
        json={"question": "Allowed by quota, should answer normally"},
    )
    assert res.status_code == 200
    assert res.json()["data"]["answer"]


# ---------- GET /quota -------------------------------------------------


async def test_quota_route_returns_unlimited_when_no_quota_row(client, fake_db, fake_auth):
    """Org with no quota row → `unlimited=true`, both dimensions null.
    Pin so the frontend banner can rely on `unlimited` to short-circuit
    rendering instead of having to interpret null percents itself."""
    # Pre-program the SELECT to return a Result whose `.first()` is None —
    # the "no quota row" shape from the LEFT JOIN. FakeAsyncSession's
    # default execute mock doesn't set `.first()`, so without this the
    # route's `if row is None:` short-circuit never fires and the
    # MagicMock attributes TypeError on `<=` comparison.
    no_row_result = MagicMock()
    no_row_result.first.return_value = None
    fake_db.set_execute_result(no_row_result)

    res = await client.get("/api/v1/codeguard/quota")
    assert res.status_code == 200
    body = res.json()["data"]
    assert body["unlimited"] is True
    assert body["input"] is None
    assert body["output"] is None
    assert body["organization_id"] == str(fake_auth.organization_id)


async def test_quota_route_returns_per_dimension_percent_when_quota_set(client, fake_db, fake_auth):
    """Org with a quota row → both dimensions populated with usage,
    limit, and computed percent. Frontend uses the percent for the
    progress-bar fill + the yellow/red threshold checks."""
    result = MagicMock()
    result.first.return_value = MagicMock(
        in_lim=1_000_000,
        out_lim=200_000,
        in_used=500_000,
        out_used=160_000,
        period_start=__import__("datetime").date(2026, 5, 1),
    )
    fake_db.set_execute_result(result)

    res = await client.get("/api/v1/codeguard/quota")
    assert res.status_code == 200
    body = res.json()["data"]
    assert body["unlimited"] is False
    assert body["input"] == {"used": 500_000, "limit": 1_000_000, "percent": 50.0}
    assert body["output"] == {"used": 160_000, "limit": 200_000, "percent": 80.0}
    assert body["period_start"] == "2026-05-01"


async def test_quota_route_handles_null_dimension_limit(client, fake_db):
    """One dimension NULL (unlimited on that axis) → that dimension's
    `percent` is null, the other dimension's percent computed normally."""
    result = MagicMock()
    result.first.return_value = MagicMock(
        in_lim=None,  # input unlimited
        out_lim=200_000,
        in_used=999_999,  # huge, but no cap
        out_used=50_000,
        period_start=__import__("datetime").date(2026, 5, 1),
    )
    fake_db.set_execute_result(result)

    res = await client.get("/api/v1/codeguard/quota")
    body = res.json()["data"]
    assert body["input"]["limit"] is None
    assert body["input"]["percent"] is None
    assert body["output"]["percent"] == 25.0


# ---------- GET /quota/history -----------------------------------------


async def test_quota_history_returns_recent_months_with_caps(client, fake_db, fake_auth):
    """Standard happy path. Two execute calls in order:
      1. SELECT from `codeguard_org_usage` → list of period rows.
      2. SELECT from `codeguard_org_quotas` → quota row for the caps.
    The route surfaces both so the frontend can render bars proportional
    to the configured cap (the "is 800k a lot?" question).
    """
    import datetime as _dt

    history_rows = MagicMock()
    history_rows.all.return_value = [
        MagicMock(
            period_start=_dt.date(2026, 5, 1),
            input_tokens=200_000,
            output_tokens=50_000,
        ),
        MagicMock(
            period_start=_dt.date(2026, 4, 1),
            input_tokens=800_000,
            output_tokens=150_000,
        ),
    ]
    quota_row = MagicMock()
    quota_row.first.return_value = MagicMock(in_lim=1_000_000, out_lim=200_000)
    fake_db.set_execute_result(history_rows)
    fake_db.set_execute_result(quota_row)

    res = await client.get("/api/v1/codeguard/quota/history")
    assert res.status_code == 200
    body = res.json()["data"]
    assert body["organization_id"] == str(fake_auth.organization_id)
    assert body["months"] == 3  # default
    assert body["input_limit"] == 1_000_000
    assert body["output_limit"] == 200_000
    # Most-recent first; matches the SQL `ORDER BY period_start DESC`.
    assert body["history"][0] == {
        "period_start": "2026-05-01",
        "input_tokens": 200_000,
        "output_tokens": 50_000,
    }
    assert body["history"][1]["period_start"] == "2026-04-01"


async def test_quota_history_clamps_months_to_12(client, fake_db):
    """`months=10000` from a malformed UI shouldn't trigger a tenant-bounded
    full-table scan. Pin the clamp at 12 (the route's documented ceiling)."""
    history_rows = MagicMock()
    history_rows.all.return_value = []
    quota_row = MagicMock()
    quota_row.first.return_value = None
    fake_db.set_execute_result(history_rows)
    fake_db.set_execute_result(quota_row)

    res = await client.get("/api/v1/codeguard/quota/history?months=10000")
    body = res.json()["data"]
    assert body["months"] == 12, (
        "months should clamp at 12; the page is a dashboard widget, not a "
        "billing report. A higher ceiling means a single bad URL can scan "
        "the whole tenant's usage history."
    )


async def test_quota_history_clamps_months_to_at_least_1(client, fake_db):
    """`months=0` would render an empty strip with no signal about why.
    Clamp to 1 so the response is at least the current month."""
    history_rows = MagicMock()
    history_rows.all.return_value = []
    quota_row = MagicMock()
    quota_row.first.return_value = None
    fake_db.set_execute_result(history_rows)
    fake_db.set_execute_result(quota_row)

    res = await client.get("/api/v1/codeguard/quota/history?months=0")
    assert res.json()["data"]["months"] == 1


async def test_quota_history_returns_null_caps_when_no_quota_row(client, fake_db):
    """Unlimited org (no quota row) → caps come back as null. The page
    still renders the history strip without scaling-to-cap (the "no
    cap" branch of HistoryBars)."""
    history_rows = MagicMock()
    history_rows.all.return_value = []
    quota_row = MagicMock()
    quota_row.first.return_value = None
    fake_db.set_execute_result(history_rows)
    fake_db.set_execute_result(quota_row)

    res = await client.get("/api/v1/codeguard/quota/history?months=3")
    body = res.json()["data"]
    assert body["input_limit"] is None
    assert body["output_limit"] is None
    assert body["history"] == []
