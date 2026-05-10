# Runbook: Redis incident (cross-surface)

The on-call procedure when Redis is degraded or unavailable.
Critical because Redis underpins **four distinct subsystems**
that fail in different ways when it flakes — knowing which
surface is affected steers the response.

The four Redis-backed subsystems:

| Subsystem | What Redis stores | Failure mode |
| --- | --- | --- |
| **Rate limiter** (`services.rate_limit`) | Per-key bucket counts | Either every request 429s, or NO request 429s |
| **Idempotency** (`services.idempotency`) | `(key, body_hash) → IdempotencyResult` | Retried requests fire side-effects twice |
| **Activity stream** (`services.activity_stream`) | Per-channel SSE tickets + replay buffer | SSE clients can't reconnect / lose stream |
| **Cron mutex** (`services.cron_mutex`) | Per-cron lock keys | Two cron runs collide OR every cron silently skips |

**Important:** these may share a Redis or be separate
deployments. Check `apps/api/core/config.py` for the URLs
each service reads. A "Redis incident" can be all-Redis-down
OR one-of-N-Redis-down; the symptoms differ.

## First 5 minutes — identify which Redis is affected

### 1. Read the alert / customer report

The four surfaces produce distinct symptoms:

- **"Customer reports duplicate side-effects"** → idempotency
  Redis is the prime suspect. See
  [`runbook-idempotency.md`](runbook-idempotency.md).
- **"Customer reports widespread 429s OR no 429s"** → rate-
  limit Redis. See
  [`runbook-rate-limits.md`](runbook-rate-limits.md).
- **"Customer reports SSE stream broke"** → activity-stream
  Redis. (No standalone runbook yet — see "Activity stream"
  below.)
- **"Cron didn't fire / fired twice"** → cron-mutex Redis.
  See [`runbook-cron-watchdog.md`](runbook-cron-watchdog.md).
- **Multiple of the above simultaneously** → likely a single
  shared Redis instance is flaking. Cross-reference URLs in
  `core/config.py`.

### 2. Confirm Redis health

```bash
# For each Redis instance the platform uses, run:
redis-cli -u <url> PING
# Expect: PONG

# Quick stats:
redis-cli -u <url> INFO server
redis-cli -u <url> INFO memory
redis-cli -u <url> INFO replication

# Slow log:
redis-cli -u <url> SLOWLOG GET 20
```

If `PING` fails or times out, Redis itself is down. Page
infra; while you wait, see "Surface-by-surface degradation"
below for what to expect.

### 3. Check for memory pressure

A common Redis incident: memory hit `maxmemory`, eviction
policy kicked in, working set started churning. Symptoms:

- `INFO memory` shows `used_memory > maxmemory * 0.9`
- `evicted_keys` is climbing rapidly in `INFO stats`

Action:

- **Short-term**: scale Redis up (more memory).
- **Medium-term**: identify the bloat. The activity-stream
  buffer is the most likely culprit (it stores per-channel
  replay buffers; if many active streams hold large buffers,
  memory grows). Inspect:

  ```bash
  redis-cli -u <url> --bigkeys
  ```

- **Long-term**: review TTLs. Idempotency records have a
  long TTL (24h is typical); if a customer's traffic spike
  filled the namespace, those entries dominate memory.

## Surface-by-surface degradation

What the customer sees when Redis flakes, per subsystem.

### Rate limiter degradation

```
Redis flake mode      Customer sees                     Severity
---                   ---                               ---
Redis unreachable     503 (limiter init fails) OR       Mid (depends on bypass switch)
                      every request blanket-429
Redis slow (>1s)      Latency spike on every request    High (hits all customers)
Memory pressure       Evicted bucket records →          Mid (under-counts; brief abuse window)
                      bursts that should 429 don't
Replica lag (cluster) Bucket count stale → race cond.   Low (rare; eventual consistency)
```

The limiter has a bypass switch (`RATE_LIMIT_ENABLED` env
var). Flipping it lets traffic through unmetered. Tradeoff:
abuse traffic gets in. **Only use as a last resort, and only
for the time it takes to repair Redis.** See
`runbook-rate-limits.md` for diagnosis.

### Idempotency degradation

```
Redis flake mode      Customer sees                     Severity
---                   ---                               ---
Redis unreachable     Retried POST/PUT/PATCH fires      HIGH — duplicate side-effects
                      side-effect twice (cache miss)
Redis slow            Latency on every retried request  Mid (additive to handler cost)
Memory pressure /     Same as unreachable for evicted   HIGH — duplicate side-effects
eviction              keys
```

There's NO bypass switch — disabling idempotency is the same
as the failure mode. The handler's `IdempotentRoute`
dispatches transparently to the cache; if Redis is down,
every request behaves like a fresh-key request.

**Customer impact during an idempotency outage**: any
double-clicked button OR any client retry produces double
side-effects. For high-stakes operations (webhook test-fire,
key creation), this is a customer-visible bug.

**Triage during the outage**:
- Identify which endpoints are highest-stakes if duplicated
  (webhook test-fire, secret rotation). Consider feature-
  flagging them off until Redis recovers.
- For lower-stakes endpoints, accept the risk and recover
  via the audit log post-hoc.

See [`runbook-idempotency.md`](runbook-idempotency.md) for
the deeper triage of duplicate-side-effect customer reports.

### Activity stream degradation

```
Redis flake mode      Customer sees                     Severity
---                   ---                               ---
Redis unreachable     SSE connections fail to open;     Mid (UX, not data)
                      reconnects fail
Redis slow            Stream events lag                 Low
Memory pressure       Replay buffer evicted; client     Mid (clients miss events
that disconnects can't replay              they expected to replay)
```

The activity-stream surface (`/activity` endpoint, the
stream-ticket auth flow) is read-shaped UX. Customers see
"unable to connect to live updates" but core CRUD still
works. The `runbook-activity-stream.md` (if present —
otherwise this section IS the runbook) covers the recovery.

### Cron mutex degradation

```
Redis flake mode      Customer / ops sees               Severity
---                   ---                               ---
Redis unreachable     Cron acquire-lock raises;         Mid (cron skip)
                      cron tick is skipped
Redis slow            Lock-acquire timeout; same as     Mid
                      unreachable for that tick
Stale lock (no TTL)   Cron silently skipped every tick  HIGH if undetected;
                      until lock evicts                 watchdog should fire
```

The `cron_mutex` lock has a TTL. If the prior holder died
without releasing AND the TTL is too long, every subsequent
tick skips. Diagnosis:

```bash
redis-cli -u <url> KEYS 'cron_mutex:*'
redis-cli -u <url> TTL 'cron_mutex:<cron_name>'
```

If TTL is `-1` (no expiration), DELETE the key:

```bash
redis-cli -u <url> DEL 'cron_mutex:<cron_name>'
```

The next tick acquires a fresh lock. File a follow-up to
audit the mutex's TTL setting (the contract is "TTL bounds
the holder's max runtime + a safety margin").

See [`runbook-cron-watchdog.md`](runbook-cron-watchdog.md)
for the alert + the deeper triage.

## Prevention

The platform's Redis exposure is broad; minimising the blast
radius matters.

### Per-subsystem connection isolation

Each subsystem should have its own connection pool (and
ideally its own Redis URL). When the rate-limit Redis is
slow, the idempotency surface should NOT also slow down. The
configuration lives in `apps/api/core/config.py` — verify
every subsystem has an explicit URL setting OR document the
sharing.

### Failure-mode telemetry

Each Redis call site should emit a metric on failure
(timeout, connection-refused, evicted-key). The on-call
dashboard then shows "rate-limit Redis is degraded" vs
"idempotency Redis is degraded" vs "all of them" rather than
forcing a `redis-cli` session per surface.

### Bypass switches WHERE SAFE

The rate limiter has one. The cron-mutex has one (skip
mutex if Redis fails — accept the risk of concurrent runs).
The idempotency surface deliberately doesn't (the risk is
duplicate side-effects, not a brief abuse window).

When designing a new Redis-backed surface, decide the
bypass-vs-fail-closed tradeoff at design time. The
`runbook-<surface>.md` should document the choice.

## Common mistakes

### Treating "Redis is slow" as "Redis is up"

A Redis returning `PONG` after a 5s delay is unhealthy. The
limiter / idempotency caller has a connection-pool timeout;
once it's hit, the surface degrades to the "unreachable"
mode. `redis-cli -u <url> --latency-history` reveals
sustained latency.

### Disabling idempotency to "make the bug go away"

Disabling idempotency means every retry produces a duplicate.
The Redis recovery is the path; disabling is not.

### Restarting Redis without a snapshot

If memory pressure hit `maxmemory` and eviction made the
state inconsistent, restarting clears the bad state but ALSO
clears every legitimate key. Customer-visible impact:
- Idempotency: every retried request now produces a duplicate
  for the next 24h.
- Cron mutex: every cron acquires a fresh lock; ongoing runs
  may overlap.
- Rate limiter: every customer's bucket resets to full.

If a snapshot was taken pre-incident, RESTORE rather than
restart. If not, communicate the impact to customers.

### Adding capacity without addressing the root cause

A 10x Redis upgrade is a tempting fix; sometimes it just
postpones the incident. The bloat / leak / churn that hit
`maxmemory` will hit the new limit too.  The follow-up
investigation is part of the runbook, not an optional extra.

## Related code + audits + runbooks

| Surface | Lives in |
| --- | --- |
| Rate limiter | `apps/api/services/rate_limit.py` |
| Idempotency | `apps/api/services/idempotency.py` |
| Activity stream | `apps/api/services/activity_stream.py` |
| Cron mutex | `apps/api/services/cron_mutex.py` |
| Redis URL config | `apps/api/core/config.py` |
| Rate limit | [`runbook-rate-limits.md`](runbook-rate-limits.md) |
| Idempotency | [`runbook-idempotency.md`](runbook-idempotency.md) |
| Cron watchdog | [`runbook-cron-watchdog.md`](runbook-cron-watchdog.md) |
| Cron admin surface | [`runbook-cron-admin.md`](runbook-cron-admin.md) |

## What this runbook is NOT for

  * **A Postgres incident.** Different storage, different
    failure modes. PG runbook lives separately (or doesn't
    exist yet — file a gap).
  * **A "Redis URL is wrong in config" deploy issue.** That's
    a config-management bug; this runbook assumes the
    configured URL is correct.
  * **A specific surface's customer-facing diagnosis.** Use
    the per-surface runbook (rate-limits, idempotency, etc.).
    This runbook is the cross-cutting Redis-itself-is-broken
    case.
