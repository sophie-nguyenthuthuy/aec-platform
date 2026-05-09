"""API-key minting, hashing, scope checks, and rate limiting.

Three responsibilities:

  * **Mint.** Generate a new key string (`aec_` + 32 random hex chars),
    hash it, persist the `(org, name, scopes, hash, prefix)` row,
    return the plaintext to the caller exactly once. The hash is
    sha256(raw_key, hex). No salt — the raw key is already 128 bits
    of entropy, so a salt buys nothing against rainbow tables.

  * **Verify.** Given a raw key from an Authorization header, hash it
    and SELECT the row WHERE `hash = ?` AND `revoked_at IS NULL` AND
    (`expires_at IS NULL OR expires_at > NOW()`). The partial index
    on `(hash) WHERE revoked_at IS NULL` makes this O(log n).

  * **Rate-limit.** Redis token bucket per (api_key_id, minute). We
    INCR a per-minute counter with a 60s TTL. Cheap (one round trip
    per request) and gives 1-minute granularity, which is good
    enough for an integration partner — sub-minute bursts ride the
    bucket headroom.

Scope vocabulary lives in `SCOPES`. Each scope is `domain:action`,
where action is `read` (GET) or `write` (everything else). A handler
gates on a scope by adding `Depends(require_scope("projects:read"))`
to its signature.

Why this isn't `enum.StrEnum`: scopes are sometimes computed (e.g.
`f"{domain}:read"` from a generic helper), and StrEnum would force
every callsite to import the enum. A plain set + `validate_scope`
keeps the call shape ergonomic.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# Closed scope vocabulary. Add a scope here + reference it in
# `require_scope("…")` from the relevant handler. Adding a scope is
# a deploy, not a migration — kept open by the text[] column shape.
#
# Convention: `<domain>:<read|write>`. `*` is reserved for full org
# admin keys (used for one-off ops scripts; admin-only to mint).
SCOPES: frozenset[str] = frozenset(
    {
        "projects:read",
        "projects:write",
        "defects:read",
        "defects:write",
        "rfis:read",
        "rfis:write",
        "change_orders:read",
        "change_orders:write",
        "suppliers:read",
        "suppliers:write",
        "estimates:read",
        "estimates:write",
        "webhooks:admin",
        "audit:read",
        "search:read",
        "*",  # superuser — admin minting only
    }
)


# Default rate limit (req / min) when an api_key has no per-key
# override. 60/min = 1/sec sustained, with a 60-burst headroom (the
# token bucket TTLs at 60s, so a quiet partner can spike to 60 then
# settle). Tuned for typical CRM/ERP integration patterns; high-
# throughput partners get a per-key bump.
DEFAULT_RATE_LIMIT_PER_MINUTE = 60


# Prefix on every minted key. Lets log-scrubbers and `grep` quickly
# distinguish AEC keys from other secrets in the same file.
KEY_PREFIX = "aec_"


# ---------- Mint ----------


def _generate_key() -> str:
    """`aec_` + 32 random hex chars. 32 hex = 128 bits, well above
    the entropy floor for a long-lived credential. The `aec_` prefix
    makes log-scrubbers' lives easier and is also what lets us
    pattern-match the Authorization header in `verify_key`."""
    return f"{KEY_PREFIX}{secrets.token_hex(32)}"


def hash_key(raw: str) -> str:
    """sha256-hex of the raw key. No salt because the key itself is
    high-entropy random; salting buys nothing against the threat
    model (DB compromise, where the attacker has sha256 + the
    expected output and would brute-force regardless)."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def key_prefix(raw: str) -> str:
    """First 8 chars after the `aec_` prefix — what the UI shows so
    users can identify which key they're looking at without us
    re-leaking the secret."""
    body = raw.removeprefix(KEY_PREFIX)
    return body[:8]


async def mint_key(
    session: AsyncSession,
    *,
    organization_id: UUID,
    created_by: UUID | None,
    name: str,
    scopes: list[str],
    rate_limit_per_minute: int | None,
    expires_at: datetime | None,
) -> tuple[str, dict[str, Any]]:
    """Generate, persist, return `(plaintext, row_dict)`.

    The plaintext is shown to the user once. The row dict is what
    the listing page displays — no `hash`, since that's never useful
    UI data.

    Validates every scope against `SCOPES`; an unknown scope raises
    `ValueError` and the row never gets written.
    """
    for s in scopes:
        if s not in SCOPES:
            raise ValueError(f"unknown_scope: {s!r}")

    raw = _generate_key()
    h = hash_key(raw)
    prefix = key_prefix(raw)

    result = await session.execute(
        text(
            """
            INSERT INTO api_keys (
                id, organization_id, created_by, name, hash, prefix,
                scopes, rate_limit_per_minute, expires_at
            ) VALUES (
                gen_random_uuid(), :org, :created_by, :name, :hash, :prefix,
                :scopes, :rl, :expires_at
            )
            RETURNING id, name, prefix, scopes, rate_limit_per_minute,
                      created_at, expires_at, last_used_at, revoked_at
            """
        ),
        {
            "org": str(organization_id),
            "created_by": str(created_by) if created_by else None,
            "name": name,
            "hash": h,
            "prefix": prefix,
            "scopes": scopes,
            "rl": rate_limit_per_minute,
            "expires_at": expires_at,
        },
    )
    row = dict(result.mappings().one())
    return raw, row


# ---------- Verify ----------


async def verify_key(
    session: AsyncSession,
    *,
    raw: str,
    client_ip: str | None,
) -> dict[str, Any] | None:
    """Look up a key by hash. Returns the row dict (incl. org_id +
    scopes) on success, None when:
      * the key doesn't exist
      * the key was revoked
      * the key has expired

    Side effect: bumps `last_used_at` + `last_used_ip` on success.
    Done in the same query for efficiency — no separate UPDATE round
    trip on the hot path. The non-NOT-NULL columns let the UPDATE
    happen even when `client_ip` is unknown.

    The lookup uses the partial index `ix_api_keys_hash_active` so
    revoked keys never enter the hot path even when their hash
    collides (it won't — sha256 — but the partial index is also a
    correctness statement).
    """
    if not raw or not raw.startswith(KEY_PREFIX):
        return None
    h = hash_key(raw)
    result = await session.execute(
        text(
            """
            UPDATE api_keys
            SET last_used_at = NOW(),
                last_used_ip = :ip
            WHERE hash = :hash
              AND revoked_at IS NULL
              AND (expires_at IS NULL OR expires_at > NOW())
            RETURNING id, organization_id, scopes, rate_limit_per_minute,
                      name, prefix
            """
        ),
        {"hash": h, "ip": client_ip},
    )
    row = result.mappings().one_or_none()
    if row is None:
        return None
    return dict(row)


# ---------- Scope check ----------


def has_scope(key_scopes: list[str], required: str) -> bool:
    """True iff the api-key's scope set includes `required` or the
    wildcard `*`. Pulled into a helper so future changes (e.g. role
    hierarchies — `projects:write` implies `projects:read`) live in
    one place."""
    if "*" in key_scopes:
        return True
    return required in key_scopes


# ---------- Rate limit ----------


async def record_call(
    session: AsyncSession,
    *,
    api_key_id: UUID,
    success: bool,
    when: datetime | None = None,
) -> None:
    """Bump the per-minute counter for an API call.

    Writes one row per (api_key_id, minute_bucket, success); uses
    `INSERT … ON CONFLICT DO UPDATE` so concurrent calls in the same
    minute coalesce into a single row instead of stacking. The session
    is the caller's — we don't open our own because the writer runs
    inside the auth dependency that's already holding an admin
    session.

    `when` is overridable for testability; production callers leave it
    None (defaults to NOW()). Truncating to the minute happens server-
    side via `date_trunc` so two writers with slightly different
    clocks still collapse to the same bucket.

    Best-effort: any failure is swallowed and logged. A telemetry hiccup
    must not break authenticated requests.
    """
    try:
        await session.execute(
            text(
                """
                INSERT INTO api_key_calls (api_key_id, minute_bucket, success, count)
                VALUES (
                    :api_key_id,
                    date_trunc('minute', COALESCE(:when, NOW())),
                    :success,
                    1
                )
                ON CONFLICT (api_key_id, minute_bucket, success)
                DO UPDATE SET count = api_key_calls.count + 1
                """
            ),
            {
                "api_key_id": str(api_key_id),
                "success": success,
                "when": when,
            },
        )
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("api_keys.record_call failed (%s); telemetry row skipped", exc)


async def usage_for_key(
    session: AsyncSession,
    *,
    api_key_id: UUID,
    hours: int = 24,
) -> dict[str, Any]:
    """Aggregate `api_key_calls` for one key into a dashboard payload.

    Returns:
      * `total_count` — sum across the window
      * `error_count` — sum where success=false
      * `error_rate` — error_count / max(total, 1)
      * `series` — hour-bucketed `[{hour, success_count, error_count}, …]`
        for the sparkline. 24 entries for 24h, 168 for 7d, etc.
    """
    rows = (
        (
            await session.execute(
                text(
                    f"""
                    SELECT date_trunc('hour', minute_bucket) AS hour,
                           SUM(count) FILTER (WHERE success) AS success_count,
                           SUM(count) FILTER (WHERE NOT success) AS error_count
                    FROM api_key_calls
                    WHERE api_key_id = :id
                      AND minute_bucket >= NOW() - INTERVAL '{int(hours)} hours'
                    GROUP BY hour
                    ORDER BY hour ASC
                    """
                ),
                {"id": str(api_key_id)},
            )
        )
        .mappings()
        .all()
    )
    series = [
        {
            "hour": r["hour"].isoformat() if r["hour"] else "",
            "success_count": int(r["success_count"] or 0),
            "error_count": int(r["error_count"] or 0),
        }
        for r in rows
    ]
    success_total = sum(b["success_count"] for b in series)
    error_total = sum(b["error_count"] for b in series)
    total = success_total + error_total
    return {
        "total_count": total,
        "error_count": error_total,
        "error_rate": round(error_total / total, 4) if total > 0 else 0.0,
        "series": series,
    }


async def usage_top_keys(
    session: AsyncSession,
    *,
    hours: int = 24,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Cross-org "top keys by volume in the last N hours" — drives the
    `/admin/api-usage` admin page. JOINs to `api_keys` for the
    human-readable name + prefix.

    Uses `AdminSessionFactory` (BYPASSRLS) at the caller; this query
    spans every tenant. Includes revoked keys because their last
    activity is still useful audit data.
    """
    rows = (
        (
            await session.execute(
                text(
                    f"""
                    SELECT k.id, k.name, k.prefix, k.organization_id,
                           k.revoked_at IS NOT NULL AS revoked,
                           SUM(c.count)                              AS total_count,
                           SUM(c.count) FILTER (WHERE NOT c.success) AS error_count
                    FROM api_key_calls c
                    JOIN api_keys k ON k.id = c.api_key_id
                    WHERE c.minute_bucket >= NOW() - INTERVAL '{int(hours)} hours'
                    GROUP BY k.id, k.name, k.prefix, k.organization_id, k.revoked_at
                    ORDER BY total_count DESC
                    LIMIT :limit
                    """
                ),
                {"limit": limit},
            )
        )
        .mappings()
        .all()
    )
    return [
        {
            "id": str(r["id"]),
            "name": r["name"],
            "prefix": r["prefix"],
            "organization_id": str(r["organization_id"]),
            "revoked": bool(r["revoked"]),
            "total_count": int(r["total_count"] or 0),
            "error_count": int(r["error_count"] or 0),
        }
        for r in rows
    ]


async def check_rate_limit(
    redis: Any,
    *,
    api_key_id: UUID,
    limit_per_minute: int,
) -> tuple[bool, int, int]:
    """Per-minute token bucket via Redis INCR.

    Returns `(allowed, current_count, limit)`. The router uses these
    to (a) decide 429 vs continue and (b) emit standard
    `X-RateLimit-*` response headers.

    Implementation detail: bucket is `aec:apikey:rate:{key_id}:{minute}`
    where `minute` is `floor(unix_seconds / 60)`. A natural rollover
    every minute means we never have to worry about resetting — old
    keys TTL out automatically. INCR + EXPIRE in a pipeline so the
    first request of a new minute can't race a missing TTL.

    `redis` is `aioredis.Redis | None` so callers can short-circuit
    the limit when no Redis is configured (dev path) — passing None
    yields `(True, 0, limit)`.
    """
    if redis is None:
        return True, 0, limit_per_minute

    minute = int(datetime.now(UTC).timestamp()) // 60
    key = f"aec:apikey:rate:{api_key_id}:{minute}"
    # INCR + EXPIRE in a pipeline. EXPIRE is idempotent within a
    # bucket window; setting it on every call is the simplest way to
    # ensure new buckets always get a TTL.
    pipe = redis.pipeline()
    pipe.incr(key)
    pipe.expire(key, 70)  # 70s = bucket window + grace for clock skew
    count, _ = await pipe.execute()
    count_int = int(count)
    return count_int <= limit_per_minute, count_int, limit_per_minute
