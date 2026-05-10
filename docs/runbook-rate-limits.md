# Runbook: rate limits

The on-call procedure when a rate-limit alert fires OR a
customer reports `429` responses they think are wrong. Pairs
with:

  * `tests/test_rate_limit_audit.py` — every user-facing
    endpoint declares a rate-limit policy.
  * `tests/test_rate_limit_contract_pin.py` — the limiter's
    bucket capacity / hash-key shape is stable.
  * `services.rate_limit` — the limiter itself.

## What rate-limiting protects

Three distinct concerns:

1. **Platform stability** — bursting requests from one tenant
   exhaust shared resources (DB connection pool, Redis, worker
   queue). The limiter caps the burst.

2. **Per-customer fairness** — one tenant's spike shouldn't
   degrade latency for every other tenant on the shared
   instance.

3. **Brute-force / scraping resistance** — login attempts,
   public-RFQ submissions, password-reset requests. The
   limiter is the first line of defense.

The limiter is per-key (per-API-key for authed traffic,
per-IP for anonymous traffic). Keys are hashed with a
non-leakable hash (see `services.rate_limit::_hash_key`) so
the limiter's storage is safe to log.

## When a customer reports "I'm getting 429s"

Triage flow:

### 1. Confirm the 429 is from OUR limiter

The 429 might come from:
- Our limiter (the rate-limit headers are set).
- An upstream LB / CDN.
- An integration the customer is calling that itself rate-limits
  (the customer may have misread the chain).

Check the response headers the customer received:

```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1699999999
Retry-After: 30
```

If those headers are present, it's our limiter. If they're not,
the 429 came from somewhere else.

### 2. Identify the bucket the customer is hitting

The bucket key is `<api_key_or_ip>:<endpoint_class>`. Endpoint
classes group routes by limit policy — see
`services.rate_limit::_endpoint_class`. The customer's
`429` response includes:

```
X-RateLimit-Bucket: read_heavy
```

(The header is enabled in non-prod; in prod it may be omitted
to avoid surfacing internal taxonomy.)

### 3. Check the configured limit for that bucket

The bucket → limit mapping lives in
`services.rate_limit::BUCKET_POLICIES`:

| Bucket | Default limit | Window | Notes |
| --- | --- | --- | --- |
| `read_light` | 100 | 1 min | List + get endpoints |
| `read_heavy` | 30 | 1 min | Full-text search, exports |
| `write` | 60 | 1 min | POST / PUT / PATCH / DELETE |
| `auth` | 5 | 5 min | Login, password reset |
| `public` | 10 | 1 min | Public RFQ portal |

(The exact numbers may have drifted; treat the file as the
source of truth.)

### 4. Decide: legitimate spike or attack

Look at the customer's recent calls in the audit log:

```sql
SELECT created_at, action, ip
FROM audit_events
WHERE actor_api_key_id = '<key_uuid>'
  AND created_at >= NOW() - INTERVAL '15 minutes'
ORDER BY created_at;
```

Or, for unauthed traffic, the request log keyed on IP.

Patterns:

  * **Steady high-rate** with consistent action types →
    legitimate (a cron-like polling integration). Consider
    raising the customer's bucket limit (per-key override; see
    below).
  * **Bursty spike then quiet** → integration retry storm.
    Diagnose: is the customer's retry policy too aggressive?
  * **Many distinct IPs, same key** → key compromise. Revoke
    the key (see `runbook-api-keys.md`).
  * **Many distinct keys, same IP** → IP-level abuse. Add the
    IP to the LB's denylist.

### 5. If legitimate, raise the customer's limit

Per-key overrides live in the `api_keys.rate_limit_per_minute`
column (see migration `0039_api_keys_project_ids` or wherever
the column was added). Update via:

```sql
UPDATE api_keys
SET rate_limit_per_minute = <new_limit>
WHERE id = '<key_uuid>'
  AND organization_id = '<org_uuid>';
```

This affects the `write` bucket directly; for the read buckets
the override is multiplicative against the policy default.

After update, the customer's NEXT request lands in the new
bucket — no restart needed (the limiter reads the override on
every request).

## When the rate-limit audit fires red

`test_rate_limit_audit.py` catches a user-facing endpoint that
shipped without a rate-limit declaration. Triage:

1. **Read the failure message.** It names the route(s).
2. **For each, decide:**
   - **Add a rate-limit decorator** to the handler, OR
   - **The endpoint genuinely doesn't need rate-limiting**
     (pure-static-response, behind LB-level caching) → add to
     the audit's allowlist with rationale.

The audit's docstring lists the canonical declarations; follow
the convention in any sister handler.

## When the limiter itself misbehaves

Symptoms:

  * **Every request gets 429** — the limiter's Redis is down or
    its capacity calc returned 0. Check `services.rate_limit`
    init logs; verify Redis connectivity.
  * **No request EVER gets 429** — the limiter is silently
    skipping. Check that `RATE_LIMIT_ENABLED` env var is true
    (the bypass switch is intentional for staging but should
    NOT be true in prod).
  * **Limiter returns 500** — the bucket-fetch logic raised.
    Look at logs for the request-id; the `_hash_key` call may
    have been passed a None key.

The `test_rate_limit_contract_pin.py` test pins the limiter's
shape — bucket capacity clamp, key-hash invariant, deploy-time
rebuild on policy change. If that's red AND the limiter
behaves weird, the contract is the cause.

## Common mistakes

### Treating 429 as the customer's fault

The 429 might be a misconfigured limit on our side. Always
check our policy first; only raise an integration ticket with
the customer if the policy is sane and they're still hitting
it.

### Dropping limits "to debug"

Disabling the limiter in production means the next abusive
request can hit the DB without protection. Diagnose with limit
overrides on a specific key, not by toggling the global flag.

### Adding a per-key override "permanently"

Rate-limit overrides should expire. A customer who legitimately
needed 1000/min last quarter probably doesn't anymore. Audit
the override table quarterly:

```sql
SELECT k.id, k.organization_id, k.rate_limit_per_minute,
       k.last_used_at
FROM api_keys k
WHERE k.rate_limit_per_minute IS NOT NULL
  AND k.rate_limit_per_minute > <default>
ORDER BY k.last_used_at DESC;
```

Resetting unused overrides reduces the platform's exposure to
key-compromise abuse.

## Related code + audits + runbooks

| Surface | Lives in |
| --- | --- |
| Limiter implementation | `apps/api/services/rate_limit.py` |
| Rate-limit decorator | `apps/api/middleware/rate_limit_route.py` |
| Bucket policy table | `services.rate_limit::BUCKET_POLICIES` |
| Per-key override column | `api_keys.rate_limit_per_minute` |
| Audit | `tests/test_rate_limit_audit.py` |
| Contract pin | `tests/test_rate_limit_contract_pin.py` |
| API-key lifecycle | [`runbook-api-keys.md`](runbook-api-keys.md) |

## What this runbook is NOT for

  * **A 429 from an upstream service** the customer is calling.
    That's their integration; they'd need their upstream's
    runbook.
  * **A 503 from the LB.** That's load-shedding, not
    rate-limiting; different cause + different fix.
  * **Adding rate limits to a NEW endpoint.** The audit fires
    in CI; add the decorator before the PR lands. This runbook
    is for in-prod incidents.
