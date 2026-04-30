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
