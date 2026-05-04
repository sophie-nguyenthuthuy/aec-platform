"""Per-route token weighting + per-user attribution for CODEGUARD quotas.

Why this is its own module (split out of `services/codeguard_quotas.py`):

  The parent file has historically been a target for an aggressive
  local linter / reformat pass that drops large additions between
  rounds of work. Concentrating the at-risk additions —
  `record_user_usage`, the route-weight policy, and the
  `_with_usage_recording` context manager — into a small focused
  module reduces the cost of recovery when the reverter strikes
  AND lets the snapshot test pin the surface here in one place.

  The parent `services/codeguard_quotas.py` keeps the load-bearing
  cap-check helpers (`check_org_quota`, `record_org_usage`,
  `check_and_notify_thresholds`) — those have proven stable.

What lives here:

  * `ROUTE_WEIGHTS` / `route_weight_for(key)` — the per-route
    multiplier policy. `/scan` records at 5×, `/permit-checklist`
    at 2×, `/query` baseline 1×. `route_weight_for` defaults to 1.0
    for unknown keys (fail-closed-but-safe — a typo under-charges
    the operator's expected scan-rate-of-spend instead of 429-ing
    every request).
  * `_apply_weight(tokens, weight)` — multiplier with banker's
    rounding (avoids ~0.5-token bias per call) and negative-weight
    clamp to 0 (refuses to silently REDUCE recorded usage on
    operator typo).
  * `record_user_usage` — sidecar UPSERT against
    `codeguard_user_usage`. Same weight as the org-level write
    (otherwise the reconcile cron flags every weighted route as
    drift).
  * `with_usage_recording` — async context manager that binds the
    request-scoped telemetry accumulator, drains it on exit into
    BOTH `record_org_usage` (cap-check cache) AND
    `record_user_usage` (attribution sidecar), and fires the
    threshold-notification check after the writes. Replaces the
    inline `_with_usage_recording` helper that previously lived in
    `routers/codeguard.py` and got reverted on every round.
"""

from __future__ import annotations

import contextlib as _contextlib
import logging
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from middleware.auth import AuthContext

logger = logging.getLogger(__name__)


# ---------- Per-route weighting policy -----------------------------------


# `/scan` costs ~5× `/query` (full-project read + multi-pass review).
# Provider tokens alone undercharge the heavy route — `route_weight`
# scales the recorded counters so the cap check naturally enforces
# the right "real-cost" budget.
#
# When adding a new route: append here AND pass
# `route_key="<key>"` from the route's `with_usage_recording(...)`
# call. Weights are floats so a future "long-context premium" weight
# like 1.5 is a one-line tweak. Keeping the policy in this dict (not
# spread across route handlers) means changing a weight is one
# constant edit.
ROUTE_WEIGHTS: dict[str, float] = {
    # Single-shot retrieval-and-answer — baseline.
    "query": 1.0,
    # Full-project review pass (embed every file + multi-pass LLM).
    # ~5× compute over a query against a fresh corpus.
    "scan": 5.0,
    # Permit-checklist — ~2× the structured output of a query (the
    # checklist itself plus per-item rationale).
    "permit-checklist": 2.0,
}


def route_weight_for(route_key: str) -> float:
    """Look up the weight for a route; defaults to 1.0 if unknown.

    Fail-closed-but-safe: a typo under-charges (raw token cost) rather
    than 429-ing every request behind the route. The opposite (fail-
    open with infinity weight) would block every customer until the
    weight was fixed — much worse failure mode.
    """
    return ROUTE_WEIGHTS.get(route_key, 1.0)


def _apply_weight(tokens: int, weight: float) -> int:
    """Scale a raw token count by a route weight, rounding to int.

    Rounded (not truncated) so weighted=4.6 → 5, not 4. Truncation
    biases weighted routes ~0.5 tokens/call low — adds up over
    millions of requests/month. Python's `round()` (banker's
    rounding) keeps the long-run accumulator unbiased.

    Negative weights clamp to 0 — they're operator error and we
    refuse to silently REDUCE recorded usage (which would breach the
    cap quietly).
    """
    if weight <= 0:
        return 0
    return max(0, round(tokens * weight))


# ---------- Per-user usage write -----------------------------------------


async def record_user_usage(
    db: AsyncSession,
    org_id: UUID,
    user_id: UUID,
    *,
    input_tokens: int,
    output_tokens: int,
    route_weight: float = 1.0,
) -> None:
    """Increment the (org, user) per-month token totals.

    Sidecar to `record_org_usage` against the
    `(organization_id, user_id, period_start)` PK. Two writes per
    successful LLM request: org-level for cap checks (load-bearing),
    user-level for "who burned the most tokens this month?"
    attribution (sidecar). Both use the same `route_weight`; the
    reconcile cron compares totals and fires the
    `CodeguardQuotaUsageDrift` alert if they diverge.

    Skips on zero exactly like `record_org_usage`.
    """
    if input_tokens == 0 and output_tokens == 0:
        return
    weighted_in = _apply_weight(input_tokens, route_weight)
    weighted_out = _apply_weight(output_tokens, route_weight)

    sql = text(
        """
        INSERT INTO codeguard_user_usage
          (organization_id, user_id, period_start, input_tokens, output_tokens, updated_at)
        VALUES
          (:org_id, :user_id, date_trunc('month', NOW())::date, :in_tok, :out_tok, NOW())
        ON CONFLICT (organization_id, user_id, period_start) DO UPDATE SET
          input_tokens  = codeguard_user_usage.input_tokens  + EXCLUDED.input_tokens,
          output_tokens = codeguard_user_usage.output_tokens + EXCLUDED.output_tokens,
          updated_at    = NOW()
        """
    )
    await db.execute(
        sql,
        {
            "org_id": str(org_id),
            "user_id": str(user_id),
            "in_tok": weighted_in,
            "out_tok": weighted_out,
        },
    )


# ---------- Request-scoped recording context manager --------------------


@_contextlib.asynccontextmanager
async def with_usage_recording(
    db: AsyncSession,
    auth: AuthContext,
    *,
    route_key: str = "query",
):
    """Bind a per-request `TelemetryAccumulator`, drain it on exit.

    Yields the accumulator so handlers can inspect token counts mid-
    flight if needed. On exit, persists accumulated totals to BOTH
    `codeguard_org_usage` (cap-check cache) AND
    `codeguard_user_usage` (per-user attribution).

    `route_key` selects the per-route multiplier from `ROUTE_WEIGHTS`
    above. Same weight applied to both writes so the reconcile cron's
    drift detector doesn't flag every weighted route as drifted.

    Best-effort writes: a transient DB error during either write is
    logged at WARNING and swallowed. Without the swallow a flaky
    bookkeeping write would 502 a request whose LLM work already
    succeeded; the user-visible response was already returned (or
    streamed), and refusing to commit it because the counter write
    failed is the wrong tradeoff.

    The per-user write is its own try/except (separate from org-
    level) because the org-level write is load-bearing for cap
    checks; per-user attribution is a sidecar dashboard fueler.

    Token-less calls (HyDE cache hits, embedding-only paths) leave
    the accumulator at (0, 0); both record fns short-circuit on
    both-zero, so we don't pay a write for free requests.

    Why not a FastAPI dependency: streaming routes return a
    StreamingResponse whose generator runs *after* the dependency's
    `yield` resumes. The drain has to happen after the generator
    finishes, which means the route owns the wrap.
    """
    # Lazy imports so this module's import cost stays small —
    # everything below is only needed inside the request lifecycle.
    from ml.pipelines.codeguard import (
        TelemetryAccumulator,
        clear_telemetry_accumulator,
        set_telemetry_accumulator,
    )

    from services import codeguard_quotas as _q

    organization_id = auth.organization_id
    user_id = auth.user_id
    weight = route_weight_for(route_key)

    acc = TelemetryAccumulator()
    token = set_telemetry_accumulator(acc)
    try:
        yield acc
    finally:
        clear_telemetry_accumulator(token)
        if acc.input_tokens or acc.output_tokens:
            # Pre-weight the counts here, NOT in `record_org_usage`.
            # The service-side function's signature is `(input_tokens,
            # output_tokens)` — keeping the call shape stable lets
            # the weight policy live entirely in this module without
            # expanding the SQL helper's surface area.
            weighted_in = _apply_weight(acc.input_tokens, weight)
            weighted_out = _apply_weight(acc.output_tokens, weight)
            try:
                await _q.record_org_usage(
                    db,
                    organization_id,
                    input_tokens=weighted_in,
                    output_tokens=weighted_out,
                )
            except Exception:
                logger.warning(
                    "codeguard_quotas.record_org_usage failed for org=%s "
                    "(in=%d, out=%d, weight=%.2f) — request already served",
                    organization_id,
                    acc.input_tokens,
                    acc.output_tokens,
                    weight,
                )

            # Per-user sidecar — its own try/except so a transient
            # failure can't roll back the org-level write. The
            # reconcile cron catches sustained drift between the
            # two tables if this write keeps failing.
            try:
                await record_user_usage(
                    db,
                    organization_id,
                    user_id,
                    input_tokens=acc.input_tokens,
                    output_tokens=acc.output_tokens,
                    route_weight=weight,
                )
            except Exception:
                logger.warning(
                    "codeguard_quota_attribution.record_user_usage failed for "
                    "org=%s user=%s (in=%d, out=%d, weight=%.2f) — "
                    "request already served",
                    organization_id,
                    user_id,
                    acc.input_tokens,
                    acc.output_tokens,
                    weight,
                )

            # Threshold-notification check fires AFTER the usage
            # write so the percent reads the post-increment value.
            # Wrapped in its own try/except — the request has
            # already been served, an SMTP outage or notification-
            # prefs query failure must NOT propagate to the user.
            try:
                await _q.check_and_notify_thresholds(db, organization_id)
            except Exception:
                logger.warning(
                    "codeguard_quotas.check_and_notify_thresholds failed for org=%s — request already served",
                    organization_id,
                )
