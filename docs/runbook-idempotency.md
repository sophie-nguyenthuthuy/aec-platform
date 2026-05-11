# Runbook: idempotency

The on-call procedure when a customer reports duplicate
side-effects from what they thought was a single retried
request, OR when the idempotency contract audit fires red.
Pairs with:

  * `tests/test_idempotency_contract_audit.py` — every
    POST/PUT/PATCH endpoint declares an idempotency policy.
  * `tests/test_idempotency_contract_pin.py` — the body-canon
    + sha256 hashing + `FOR UPDATE` invariants are stable.
  * `services.idempotency` — the implementation.

## What idempotency protects

A retried request that the customer thinks failed (because the
network dropped the response) MUST NOT fire the side-effect
twice. Without idempotency:

  * `POST /webhooks/{id}/test` → two test events fire.
  * `POST /api-keys` → two keys created with the same
    creation request.
  * `POST /webhooks/deliveries/{id}/redeliver` → operator
    double-clicks → two deliveries fire.

The platform's idempotency contract:

  1. The client sends an `Idempotency-Key` header (UUID or
     opaque string per the partner's choice).
  2. The first request with that key + body hash creates the
     resource AND records `(key, body_hash) →
     IdempotencyResult` in Redis.
  3. A subsequent request with the same key + body returns
     the cached result. The server-side mutation does NOT
     re-fire.
  4. A request with the same key but a DIFFERENT body returns
     `409 Conflict` with `IdempotencyKeyMismatch`. The client
     must use a new key for genuinely different requests.

The TTL on the Redis record is documented in
`services.idempotency` — long enough that a network-retry
window is covered (24h is typical), short enough that the
record set doesn't grow unbounded.

## When a customer reports "I got two charges / two events"

### 1. Confirm the duplicate is real

Pull the audit-log rows for the resource:

```sql
SELECT created_at, request_id, action, before, after
FROM audit_events
WHERE resource_type = '<type>'
  AND resource_id = '<uuid>'
  AND organization_id = '<org_uuid>'
ORDER BY created_at;
```

Two rows with the SAME `request_id` would be impossible (each
request gets a unique request_id). Two rows with DIFFERENT
request_ids but the same action close in time → likely two
genuine requests, not one retried one.

### 2. Check the Idempotency-Key header

If the customer's client logs include the `Idempotency-Key`
header value, confirm it's the same on both calls:

  * **Same key, both requests succeeded with different bodies**
    → the key was reused for genuinely different content.
    That's a customer-side bug; their retry logic is keying on
    a request-shape that varies. Document the
    Idempotency-Key contract in their integration.
  * **Same key, both requests succeeded with same body** → our
    bug. The cached `IdempotencyResult` should have prevented
    the second mutation. Diagnose below.
  * **Different keys** → the customer's client generated a new
    key per retry. Their library is broken (the typical pattern
    is "one key per logical operation, retried until success").

### 3. If our bug: diagnose the cached-result miss

Three causes:

  * **Cache evicted before the retry.** TTL too short for the
    retry window. Check `services.idempotency`'s TTL constant;
    if the customer retried 25 hours after the original and
    TTL is 24h, the cache had already evicted. Solution:
    extend TTL OR direct the customer to retry within the
    documented window.

  * **Body-canonicalisation mismatch.** Same logical body but
    JSON serialised differently (key ordering, whitespace) →
    different sha256 → cache miss. The contract pin
    (`test_idempotency_contract_pin.py`) covers
    canonicalisation; if it's green, the canonicaliser is
    working. Look for the customer sending genuinely different
    bytes (different escape sequences, different float
    precision).

  * **Redis itself was unavailable.** Idempotency records
    couldn't be read; the handler fell through to the original
    create path. Check Redis health metrics for the affected
    timestamp range.

## When the idempotency contract audit fires red

`test_idempotency_contract_audit.py` catches a POST/PUT/PATCH
endpoint that shipped without an idempotency policy. Triage:

1. **Read the failure.** It names the route(s).
2. **For each, decide:**
   - **The endpoint mutates state** → add the
     `IdempotentRoute` route_class to the router, OR add
     idempotency handling per the convention.
   - **The endpoint is idempotent by virtue of its semantic**
     (PUT to a fixed URL with full state — same call always
     produces same result) → add to the audit's allowlist
     with rationale.
   - **The endpoint is read-shaped POST** (a search-via-POST
     because the query is too large for a URL) → add to the
     allowlist with rationale.

## When `409 IdempotencyKeyMismatch` fires unexpectedly

The customer reused a key with a different body. The server's
response should include enough to diagnose:

```json
{
  "error": "IdempotencyKeyMismatch",
  "message": "...",
  "details_url": "/docs/api#idempotency"
}
```

The customer's integration is reusing keys across logical
operations. Their retry logic should generate a new key per
intended operation, not per HTTP-call.

## When `FOR UPDATE` lock contention shows up

The idempotency contract uses `FOR UPDATE` locking on the
idempotency record so concurrent retries serialize cleanly
(only one of N concurrent requests fires the side-effect; the
others wait + return the same `IdempotencyResult`).

Symptoms of contention:

  * Slow `POST /...` requests where the body is the
    Idempotency-Key match for an in-flight request. Expected
    behavior — the second request waits for the first to
    finish, then returns the cached result.

  * Lock-acquire timeouts. The Redis layer's lock acquisition
    has a short timeout; if a 5xx fires from the lock, the
    customer can retry and the next attempt should succeed.

If the contention is causing customer-facing issues (latency
spikes during burst traffic), look at the request timing — a
slow-to-finish first request is making concurrent retries wait.
The fix is making the FIRST request faster, not relaxing
idempotency.

## When idempotency records grow unbounded

The Redis layer has a TTL on every record. If records aren't
expiring, the TTL set isn't propagating. Diagnose:

```bash
# Look at sample idempotency keys in Redis
redis-cli SCAN 0 MATCH 'idempotency:*' COUNT 10
# For one, check TTL:
redis-cli TTL 'idempotency:<key>'
```

If TTL is `-1` (no expiration), the writer isn't setting one.
That's a contract pin failure (`test_idempotency_contract_pin.py`)
— check the test result on the deploy that introduced the bug.

If TTL is set but the count is huge, the TTL may be too long.
Audit the storage cost vs the realistic retry window.

## Common mistakes

### Reusing keys across logical operations

The Idempotency-Key contract is one-key-per-logical-operation.
A customer's client that uses the same key for "create
subscription" AND "update subscription" will see one of them
silently no-op (the second hits the cached result of the
first).

### Treating idempotency as deduplication

Two genuinely different requests (different keys) that produce
the same side-effect aren't deduplicated. Idempotency is about
retry safety, not deduplication.

### Generating keys server-side

The key has to come from the CLIENT — they generate it before
the request, send it on every retry of THAT request. A
server-generated key defeats the purpose (the server never
sees the SAME key on a retry; it generates a new one).

## Related code + audits + runbooks

| Surface | Lives in |
| --- | --- |
| Idempotency service | `apps/api/services/idempotency.py` |
| Route class | `apps/api/middleware/idempotency_route.py::IdempotentRoute` |
| Contract pin | `tests/test_idempotency_contract_pin.py` |
| Audit | `tests/test_idempotency_contract_audit.py` |
| Webhook delivery use | [`runbook-webhook-deliveries.md`](runbook-webhook-deliveries.md) |
| Audit log query | [`runbook-audit-trail.md`](runbook-audit-trail.md) |

## What this runbook is NOT for

  * **A general retry-storm incident.** That's a rate-limit
    concern; see [`runbook-rate-limits.md`](runbook-rate-limits.md).
  * **Webhook-delivery dedup.** That uses idempotency
    internally but the operational surface is different —
    see [`runbook-webhook-deliveries.md`](runbook-webhook-deliveries.md).
  * **Adding idempotency to a new endpoint.** The audit fires
    in CI; declare the policy before merge. This runbook is for
    in-prod incidents.
