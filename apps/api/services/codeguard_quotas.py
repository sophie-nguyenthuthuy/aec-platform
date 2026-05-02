"""Per-org token quota enforcement for CODEGUARD LLM calls.

Two narrow concerns:
  1. Pre-flight: read an org's accumulated tokens for the current month
     against their configured limit; raise 429 when over.
  2. Post-call: increment the org's running total by whatever the
     request actually consumed, sourced from the telemetry accumulator
     populated during `_record_llm_call`.

Both run inside the route layer's `_telemetry_ctx_dep`, not inside the
pipeline. Keeping enforcement out of the pipeline keeps `pipelines/
codeguard.py` tenant-agnostic — the same module continues to work
under CLI scripts and tests where there's no org_id at all.

The telemetry helper (`pipelines.codeguard._record_llm_call`) attaches
captured token counts to `_telemetry_accumulator` (a `ContextVar`) in
addition to its existing log emission. The quota dep reads that
accumulator at request end and writes the totals to
`codeguard_org_usage`. Single source of truth: tokens land in both
places (telemetry log + quota counter) from the same handler.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class QuotaCheckResult:
    """Outcome of a quota pre-flight.

    `over_limit` is True only when both (a) a quota row exists for the
    org AND (b) at least one of the configured limits has been crossed.
    Missing quota row → `over_limit=False`, `limit_kind="unlimited"`.
    """

    over_limit: bool
    limit_kind: str  # "unlimited" | "input" | "output"
    used: int  # tokens used on the binding dimension (0 when unlimited)
    limit: int | None  # configured cap on the binding dimension


async def check_org_quota(db: AsyncSession, org_id: UUID) -> QuotaCheckResult:
    """Read the org's quota + current-month usage, return whether they're over.

    Single round-trip: a JOIN against `codeguard_org_quotas` and
    `codeguard_org_usage` on the current period. Either row can be
    missing — the LEFT JOIN handles both:
      * No quota row → unlimited.
      * Quota row but no usage row → 0 used, not over.

    Why we don't cache: quota rows change rarely but usage rows change
    on every successful LLM call. A request-scoped cache would be safe;
    a longer-lived one would risk letting an org spend past their limit
    by the time the cache TTL expired. For now, one query per request
    — cheap (PK lookup) and never wrong.
    """
    sql = text(
        """
        SELECT
          q.monthly_input_token_limit,
          q.monthly_output_token_limit,
          COALESCE(u.input_tokens, 0)  AS input_used,
          COALESCE(u.output_tokens, 0) AS output_used
        FROM codeguard_org_quotas q
        LEFT JOIN codeguard_org_usage u
          ON u.organization_id = q.organization_id
          AND u.period_start = date_trunc('month', NOW())::date
        WHERE q.organization_id = :org_id
        """
    )
    row = (await db.execute(sql, {"org_id": str(org_id)})).first()

    # No quota row → unlimited. This is the opt-in behaviour: orgs
    # aren't blocked retroactively when this migration lands; only
    # those explicitly assigned a limit get checked.
    if row is None:
        return QuotaCheckResult(over_limit=False, limit_kind="unlimited", used=0, limit=None)

    in_limit = row.monthly_input_token_limit
    out_limit = row.monthly_output_token_limit
    in_used = row.input_used
    out_used = row.output_used

    # Check each dimension independently. The "binding" dimension —
    # the one that's actually pinning the org — gets returned in
    # `limit_kind` so the 429 response message can point at the right
    # cap (helpful for debugging "why am I getting blocked when I'm
    # only at 60% of input quota?").
    if in_limit is not None and in_used >= in_limit:
        return QuotaCheckResult(over_limit=True, limit_kind="input", used=in_used, limit=in_limit)
    if out_limit is not None and out_used >= out_limit:
        return QuotaCheckResult(over_limit=True, limit_kind="output", used=out_used, limit=out_limit)
    return QuotaCheckResult(over_limit=False, limit_kind="unlimited", used=0, limit=None)


async def record_org_usage(
    db: AsyncSession,
    org_id: UUID,
    *,
    input_tokens: int,
    output_tokens: int,
) -> None:
    """Increment the org's current-month token totals.

    UPSERT against `(organization_id, period_start)` — the migration's
    composite PK guarantees one row per (org, month). Concurrent
    requests for the same org in the same month converge correctly:
    `ON CONFLICT DO UPDATE` with `tokens + EXCLUDED.tokens` is
    associative, no double-counting.

    Skips entirely when both counts are zero — happens when every LLM
    call in the request was a HyDE cache hit (no telemetry record =
    no token attribution). Avoids touching the DB for free requests.
    """
    if input_tokens == 0 and output_tokens == 0:
        return

    sql = text(
        """
        INSERT INTO codeguard_org_usage
          (organization_id, period_start, input_tokens, output_tokens, updated_at)
        VALUES
          (:org_id, date_trunc('month', NOW())::date, :in_tok, :out_tok, NOW())
        ON CONFLICT (organization_id, period_start) DO UPDATE SET
          input_tokens  = codeguard_org_usage.input_tokens  + EXCLUDED.input_tokens,
          output_tokens = codeguard_org_usage.output_tokens + EXCLUDED.output_tokens,
          updated_at    = NOW()
        """
    )
    await db.execute(
        sql,
        {
            "org_id": str(org_id),
            "in_tok": input_tokens,
            "out_tok": output_tokens,
        },
    )


# ---------- Threshold notifications ----------------------------------------
#
# After every successful `record_org_usage`, we check whether the running
# total just crossed 80% or 95% on either dimension this month and, if so,
# email the org's `quota_warn` opt-in list. Dedupe lives in
# `codeguard_quota_threshold_notifications` (composite PK on
# org_id+dimension+threshold+period_start) — exactly one email per
# (org, dimension, threshold, period). A flapping refresh that re-records
# the same usage 100 times in a minute won't multiply emails.
#
# The check is split from the write so callers can opt out (CLI batch
# imports, tests) without paying the mailer cost. The route layer wires
# them together by calling both in sequence.

# Stable, ordered list of thresholds. Adding 50% later is one append.
# Iterated descending so we attempt the higher band first — if both 80
# AND 95 are newly crossed in the same call (a single huge request), the
# user gets the more-urgent email and the 80% INSERT later short-
# circuits via the dedupe PK.
_THRESHOLDS_PCT: tuple[int, ...] = (95, 80)


@dataclass(frozen=True)
class _ThresholdEvent:
    """One newly-crossed threshold for one dimension."""

    dimension: str  # "input" | "output"
    threshold: int  # 80 | 95
    used: int
    limit: int
    percent: float


async def _crossed_thresholds(
    db: AsyncSession,
    org_id: UUID,
) -> list[_ThresholdEvent]:
    """Return the list of (dimension, threshold) bands that the org has
    crossed THIS PERIOD but for which no notification row exists yet.

    Reads the same `codeguard_org_quotas` JOIN `codeguard_org_usage`
    shape as `check_org_quota`, then filters out (a) thresholds whose
    percent isn't yet crossed and (b) thresholds with an existing
    dedupe row for this period.

    The dedupe filter is a single LEFT JOIN — keeps the round-trip
    count to one regardless of how many thresholds fired. A version
    that issued one SELECT per (dim, threshold) would balloon to
    8 round trips per `record_org_usage` call once we add a 50%
    band, which would meaningfully inflate p95 on every LLM route.
    """
    sql = text(
        """
        SELECT
          q.monthly_input_token_limit  AS in_lim,
          q.monthly_output_token_limit AS out_lim,
          COALESCE(u.input_tokens, 0)  AS in_used,
          COALESCE(u.output_tokens, 0) AS out_used,
          COALESCE(u.period_start, date_trunc('month', NOW())::date) AS period_start
        FROM codeguard_org_quotas q
        LEFT JOIN codeguard_org_usage u
          ON u.organization_id = q.organization_id
          AND u.period_start = date_trunc('month', NOW())::date
        WHERE q.organization_id = :org_id
        """
    )
    row = (await db.execute(sql, {"org_id": str(org_id)})).first()
    if row is None:
        # Unlimited org → no thresholds to fire.
        return []

    period_start = row.period_start

    # Compute percents per dimension, skipping unlimited (None) limits.
    percents: list[tuple[str, int, int, float]] = []
    if row.in_lim is not None and row.in_lim > 0:
        percents.append(("input", row.in_used, row.in_lim, 100.0 * row.in_used / row.in_lim))
    if row.out_lim is not None and row.out_lim > 0:
        percents.append(("output", row.out_used, row.out_lim, 100.0 * row.out_used / row.out_lim))

    # Candidate (dim, threshold) bands the org has crossed.
    candidates: list[_ThresholdEvent] = []
    for dim, used, limit, pct in percents:
        for t in _THRESHOLDS_PCT:
            if pct >= t:
                candidates.append(_ThresholdEvent(dimension=dim, threshold=t, used=used, limit=limit, percent=pct))
    if not candidates:
        return []

    # Filter out thresholds that already have a dedupe row this period.
    # One round-trip: pull the entire set of "already sent" rows for
    # this org+period and subtract.
    sent_rows = (
        await db.execute(
            text(
                """
                SELECT dimension, threshold
                FROM codeguard_quota_threshold_notifications
                WHERE organization_id = :org_id
                  AND period_start = :period_start
                """
            ),
            {"org_id": str(org_id), "period_start": period_start},
        )
    ).all()
    already_sent = {(r.dimension, r.threshold) for r in sent_rows}
    return [c for c in candidates if (c.dimension, c.threshold) not in already_sent]


async def _claim_threshold_or_skip(
    db: AsyncSession,
    org_id: UUID,
    *,
    dimension: str,
    threshold: int,
    period_start: Any,
) -> bool:
    """Atomically reserve the right to send this notification.

    Insert into the dedupe table; ON CONFLICT means another concurrent
    call already claimed it. Returns True iff WE were the one to land
    the row — only then should the caller actually send the email.

    This is the single point where dedupe is decided. Calling
    `_crossed_thresholds` and then a separate `INSERT` would race: two
    concurrent `record_org_usage` calls for the same org could both
    see "no row exists yet" and both send. The INSERT…ON CONFLICT here
    closes that race because exactly one INSERT succeeds; the other
    gets DO NOTHING and we observe `rowcount == 0`.
    """
    result = await db.execute(
        text(
            """
            INSERT INTO codeguard_quota_threshold_notifications
                (organization_id, dimension, threshold, period_start)
            VALUES
                (:org_id, :dimension, :threshold, :period_start)
            ON CONFLICT DO NOTHING
            """
        ),
        {
            "org_id": str(org_id),
            "dimension": dimension,
            "threshold": threshold,
            "period_start": period_start,
        },
    )
    # `rowcount` is 1 on a fresh insert, 0 on the ON CONFLICT path.
    return getattr(result, "rowcount", 0) == 1


async def check_and_notify_thresholds(
    db: AsyncSession,
    org_id: UUID,
    *,
    mailer: Any | None = None,
    slacker: Any | None = None,
) -> list[dict[str, Any]]:
    """Notify if the org just crossed any (dimension, threshold) band.

    For each newly-crossed band: claim the dedupe row (single INSERT;
    if another worker beat us, we silently skip), then resolve
    `quota_warn` opt-in recipients from `notification_preferences` and
    fan out per channel — email if `email_enabled=TRUE`, Slack if
    `slack_enabled=TRUE`. The same user can be on both channels (or
    neither, in which case the dedupe row still lands so we don't
    re-attempt later).

    Returns a list of `{dimension, threshold, recipients, delivered_email,
    delivered_slack}` summaries — useful for the route layer / cron to
    log what fired per channel. The Slack channel uses the global ops
    webhook (`Settings.ops_slack_webhook_url`); a tenant-scoped per-org
    webhook is a future feature, not yet wired.

    `mailer` and `slacker` parameters are the `send_mail` / `send_slack`
    callables; parameterised for tests so they can pass stubs. Defaults
    to the real implementations.

    Failure mode: either channel can be down independently — a missing
    Slack webhook or an SMTP outage just records `delivered=False` for
    that channel without short-circuiting the other. The dedupe row is
    committed once per (org, dim, threshold, period) regardless. We
    chose attempt-once-per-channel because the alternative ("retry
    until delivered on every channel") trades "occasional missed
    alert" for "unbounded duplicate alerts," and finance/admin will
    tolerate the former far more than the latter.
    """
    if mailer is None:
        from services.mailer import send_mail as _send

        mailer = _send
    if slacker is None:
        from services.slack import send_slack as _slack_send

        slacker = _slack_send

    events = await _crossed_thresholds(db, org_id)
    if not events:
        return []

    # Snapshot period_start so we use the same date across the
    # `_claim` calls — `NOW()` could in theory roll over between calls
    # if the request straddles midnight UTC on the 1st. Reading once
    # here guarantees consistent dedupe semantics.
    period_start_row = (await db.execute(text("SELECT date_trunc('month', NOW())::date AS p"))).first()
    period_start = period_start_row.p

    summaries: list[dict[str, Any]] = []
    for ev in events:
        claimed = await _claim_threshold_or_skip(
            db,
            org_id,
            dimension=ev.dimension,
            threshold=ev.threshold,
            period_start=period_start,
        )
        if not claimed:
            # Lost the race to a concurrent call. Don't send.
            continue

        recipients = await _quota_warn_recipients(db, org_id)
        if not recipients:
            # Nobody opted in. The claim row is already committed so
            # we won't re-fire later — but record the no-op in the
            # return summary so the caller can surface "warned but
            # nobody listening" in their logs.
            summaries.append(
                {
                    "dimension": ev.dimension,
                    "threshold": ev.threshold,
                    "recipients": [],
                    "delivered_email": 0,
                    "delivered_slack": 0,
                }
            )
            continue

        # Render once per event — every recipient gets the same body.
        subject, text_body, html_body = _render_threshold_email(
            dimension=ev.dimension,
            threshold=ev.threshold,
            used=ev.used,
            limit=ev.limit,
            percent=ev.percent,
        )

        delivered_email = 0
        delivered_slack = 0
        slack_already_fired = False  # global webhook → fire at most once per event
        for r in recipients:
            if r.email_enabled and r.email:
                d = await mailer(
                    to=r.email,
                    subject=subject,
                    text_body=text_body,
                    html_body=html_body,
                )
                if d.get("delivered"):
                    delivered_email += 1
            if r.slack_enabled and not slack_already_fired:
                # Single global webhook for now — posting once per
                # opted-in user would spam the same channel N times.
                # Pin "at most one Slack post per (event, org)" so the
                # fan-out behaves sanely until we add per-user Slack
                # destinations (DM webhooks, etc.).
                slack_already_fired = True
                fallback_text, blocks = _render_threshold_slack(
                    dimension=ev.dimension,
                    threshold=ev.threshold,
                    used=ev.used,
                    limit=ev.limit,
                    percent=ev.percent,
                )
                d = await slacker(text=fallback_text, blocks=blocks)
                if d.get("delivered"):
                    delivered_slack = 1

        summaries.append(
            {
                "dimension": ev.dimension,
                "threshold": ev.threshold,
                # `recipients` keeps the email list shape callers used
                # to expect — the per-user channel breakdown lives
                # in the structured fields below. Backwards-compat
                # for any caller that just wants "who got pinged."
                "recipients": [r.email for r in recipients if r.email_enabled and r.email],
                "delivered_email": delivered_email,
                "delivered_slack": delivered_slack,
            }
        )

    return summaries


@dataclass(frozen=True)
class _Recipient:
    """One user's per-channel notification intent. Built from
    `notification_preferences` JOIN `users`."""

    email: str | None
    email_enabled: bool
    slack_enabled: bool


async def _quota_warn_recipients(db: AsyncSession, org_id: UUID) -> list[_Recipient]:
    """Return the per-user channel intent for `quota_warn`.

    Different shape from before: previously returned `list[str]` of
    emails. Now returns `list[_Recipient]` so the dispatcher can fan
    out per channel — a user with `slack_enabled=TRUE, email_enabled=
    FALSE` was previously dropped on the floor; now they get a Slack
    post.

    Includes users with NEITHER channel enabled (the rare "I want a
    row but disabled both" state). The caller filters per-channel,
    so they're a no-op rather than a crash. Lets the dedupe row still
    land for that opted-out-of-everything user, which preserves the
    "exactly once attempted" contract."""
    rows = (
        await db.execute(
            text(
                """
                SELECT
                  u.email           AS email,
                  p.email_enabled   AS email_enabled,
                  p.slack_enabled   AS slack_enabled
                FROM notification_preferences p
                JOIN users u ON u.id = p.user_id
                WHERE p.organization_id = :org_id
                  AND p.key = 'quota_warn'
                  AND (p.email_enabled = TRUE OR p.slack_enabled = TRUE)
                """
            ),
            {"org_id": str(org_id)},
        )
    ).all()
    return [
        _Recipient(
            email=r.email,
            email_enabled=bool(r.email_enabled),
            slack_enabled=bool(r.slack_enabled),
        )
        for r in rows
    ]


def _format_vi_int(n: int | None) -> str:
    """vi-VN dot grouping (`1.500.000`). Mirrors the helper in
    `routers.codeguard` so the email copy matches the toast / banner
    numbers users see elsewhere. Kept duplicated rather than imported
    to avoid a circular dep (services → routers)."""
    if n is None:
        return "?"
    return f"{n:,d}".replace(",", ".")


def _quota_page_url() -> str:
    """Build the absolute URL for the in-app quota planning page.

    Resolved at email-render time (not module import) so a settings
    override in tests / different deploy environments takes effect
    without a service restart. Strips trailing slash on the base so
    callers can rely on `<base>/codeguard/quota` being well-formed
    regardless of how the env var is set.

    Why absolute and not relative: most email clients (Gmail, Outlook
    web, Apple Mail) render `<a href="/path">` as non-clickable text
    because the message has no host context. The same `href` works
    fine when copied into a browser, but the in-email click — the
    one we built the CTA for — silently does nothing.
    """
    from core.config import get_settings

    base = get_settings().web_base_url.rstrip("/")
    return f"{base}/codeguard/quota"


def _render_threshold_email(
    *,
    dimension: str,
    threshold: int,
    used: int,
    limit: int,
    percent: float,
) -> tuple[str, str, str]:
    """Build the threshold email payload.

    Two thresholds, two distinct tones:
      * 80% → warn ("approaching cap, plan ahead")
      * 95% → critical ("imminent — next request may 429")

    Returns (subject, text_body, html_body). HTML is single-string
    inline (same pattern as `services/notifications.py`) so the mailer
    doesn't need a template engine. Both the text and HTML bodies
    embed the absolute `web_base_url`-prefixed link to /codeguard/quota
    — relative paths render as inert text in most email clients.
    """
    is_critical = threshold >= 95
    used_fmt = _format_vi_int(used)
    limit_fmt = _format_vi_int(limit)
    quota_url = _quota_page_url()

    if is_critical:
        subject = f"CODEGUARD: Sắp đạt hạn mức tháng — {dimension} ở {percent:.1f}%"
        headline = f"Sắp đạt hạn mức {dimension} tháng này"
        body_intro = (
            f"Tổ chức của bạn đã sử dụng {percent:.1f}% hạn mức token {dimension} "
            f"trong tháng này ({used_fmt} / {limit_fmt}). "
            f"Yêu cầu tiếp theo có thể bị chặn (HTTP 429)."
        )
    else:
        subject = f"CODEGUARD: Đã dùng {percent:.1f}% hạn mức {dimension} tháng này"
        headline = f"Cảnh báo hạn mức {dimension}"
        body_intro = (
            f"Tổ chức của bạn đã sử dụng {percent:.1f}% hạn mức token {dimension} "
            f"trong tháng này ({used_fmt} / {limit_fmt}). "
            f"Hạn mức sẽ reset đầu tháng sau, hoặc bạn có thể tăng cap qua quản trị."
        )

    text_body = f"{headline}\n\n{body_intro}\n\nXem chi tiết: {quota_url}\n"
    html_body = (
        f'<div style="font-family:system-ui,sans-serif;color:#222;max-width:560px">'
        f'<h2 style="margin:0 0 8px;font-size:16px">{headline}</h2>'
        f'<p style="font-size:13px;line-height:1.5">{body_intro}</p>'
        f'<p style="margin-top:16px;font-size:13px">'
        f'<a href="{quota_url}">Xem hạn mức chi tiết</a>'
        f"</p>"
        f"</div>"
    )
    return subject, text_body, html_body


def _render_threshold_slack(
    *,
    dimension: str,
    threshold: int,
    used: int,
    limit: int,
    percent: float,
) -> tuple[str, list[dict[str, Any]]]:
    """Build the (fallback_text, blocks) pair for a threshold Slack post.

    Mirrors the structure of `_render_threshold_email` (same vi-VN
    copy, same critical/warn split) but renders to Slack Block Kit
    so the message looks native — and falls back gracefully on
    receivers that don't render blocks (the `text` is the universal
    display field, used by the IDE preview, mobile notifications,
    and any plain-text Slack client).

    Mirrors the existing `render_slack_drift_alert` shape from
    `services/slack.py`.
    """
    is_critical = threshold >= 95
    used_fmt = _format_vi_int(used)
    limit_fmt = _format_vi_int(limit)
    quota_url = _quota_page_url()

    if is_critical:
        # `:rotating_light:` is the Slack-conventional emoji for
        # "this is the urgent one" — picks the same color band as
        # the `red` banner in the codeguard layout.
        text = f":rotating_light: CODEGUARD: Sắp đạt hạn mức tháng — {dimension} ở {percent:.1f}%"
        headline = f":rotating_light: Sắp đạt hạn mức {dimension}"
        intro = (
            f"Đã dùng {percent:.1f}% hạn mức token {dimension} "
            f"({used_fmt} / {limit_fmt}). "
            f"Yêu cầu tiếp theo có thể bị chặn (HTTP 429)."
        )
    else:
        text = f":warning: CODEGUARD: Đã dùng {percent:.1f}% hạn mức {dimension} tháng này"
        headline = f":warning: Cảnh báo hạn mức {dimension}"
        intro = (
            f"Đã dùng {percent:.1f}% hạn mức token {dimension} ({used_fmt} / {limit_fmt}). Hạn mức reset đầu tháng sau."
        )

    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": headline, "emoji": True},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": intro},
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"<{quota_url}|Xem hạn mức chi tiết>",
                }
            ],
        },
    ]
    return text, blocks
