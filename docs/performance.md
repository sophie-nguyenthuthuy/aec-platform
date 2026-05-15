# Performance — caching, pooling, perf budget

How AEC Platform stays fast as customer count grows. Three pillars:

  1. **Cache hot reads in Redis** (covers `/me/orgs`,
     `/billing/current`, `/my-work/summary`).
  2. **Postgres connection pool tuning** — sized to the workload mix.
  3. **Per-endpoint perf budget** + slow-query alerting.

---

## 1. Read cache (Redis-backed)

### What's cached

| Surface | Key | TTL | Invalidated on |
|---|---|---|---|
| `/me/orgs` | `aec:cache:user:{uid}:orgs` | 30s | org create, member added/removed |
| `/billing/current` | `aec:cache:org:{org}:billing:current` | 60s | plan change, stripe webhook, vietqr confirm |
| `/my-work/summary` | `aec:cache:user:{uid}:my-work:summary` | 30s | task/activity status flip |
| `/projects` list | `aec:cache:org:{org}:projects:p{page}` | 60s | project create/update/delete |

### What's NOT cached

* **Auth (JWT verification)** — already in-memory via JWKS cache.
* **Writes** — pure pass-through.
* **pgvector retrieval** (CodeGuard, Drawbridge) — Redis can't replicate
  the vector math. We rely on HNSW index + admin-tuned `ef_search`.
* **Per-request audit log writes** — audit_events must hit Postgres
  durably; no caching.

### Cache module surface

```python
from core.cache import get_or_compute, invalidate, invalidate_org_surface

# Read path
async def list_my_orgs(user):
    return await get_or_compute(
        ("user", user.user_id, "orgs"),
        _fetch_memberships,
        ttl_seconds=30,
    )

# Write path
async def create_org(...):
    # ... do the insert ...
    await invalidate("user", user.user_id, "orgs")
```

Pattern delete (drop every entry for one org's surface):

```python
await invalidate_org_surface(org_id, "projects")
```

Uses Redis `SCAN` not `KEYS *` — bounded + non-blocking. Capped at
1000 keys per call (typo defense).

### Fail-open guarantee

Redis outage → `_get_pool()` returns None → cache becomes a hard
no-op + every request hits the DB. **A cache outage never produces a
500.** Tested by `tests/test_cache.py::test_redis_unavailable_falls_through_to_compute`.

---

## 2. Postgres connection pool

### Current sizing (production)

* `engine` (runtime, request-scoped via `aec_app` role):
  `pool_size=10, max_overflow=20`. Per-API-replica. 3 replicas →
  90 connections total (within Supabase pooler's 200 cap).
* `_admin_engine` (cross-tenant batch jobs, `aec` superuser):
  `pool_size=5, max_overflow=10`. Per-worker-replica.

### When to tune

| Symptom | Likely cause | Fix |
|---|---|---|
| `QueuePool limit of size 10 overflow 20 reached` | Request bursts > pool | Raise `max_overflow`. Cheap. |
| `connection_limit_for_role exceeded` | Total pool * replicas > DB cap | Lower `pool_size` per replica OR enable Supabase pooler in `transaction` mode |
| Slow queries piling up | Long-held connection (forgot `await session.close()`?) | Audit `db.session.TenantAwareSession` usage; ensure `async with` everywhere |
| `pool_pre_ping` warnings | Stale connection from cold-standby DB | Already enabled; should self-heal |

### Supabase pooler modes

* **Session mode** (default): each app connection = one Postgres
  connection. Use for everything except cron-fanout workers.
* **Transaction mode**: pool multiplexes — many app connections share
  a small Postgres connection set. Use for the worker service when
  cron-fanout queries swamp the connection limit.

Set `DATABASE_URL` to the pool-specific URL (port 6543 for txn mode,
5432 for session mode).

---

## 3. Per-endpoint perf budget

The `slow_query_ms` alert (`apps/api/core/observability.py::install_slow_query_listener`)
emits a WARN log when any SQL takes longer than `SLOW_QUERY_MS`
(default 500ms in prod). These warnings feed Sentry's "slow query"
issues with the SQL text + request_id.

### Soft budgets (warn at p99)

| Endpoint | Soft p99 | Hard p99 |
|---|---|---|
| `GET /me/orgs` (cached) | 5ms | 50ms |
| `GET /projects` (cached, page 1) | 30ms | 200ms |
| `GET /pulse/{id}/dashboard` (11-way fan-out) | 100ms | 500ms |
| `POST /codeguard/scan` (LLM-bound) | 3s | 15s |
| `POST /drawbridge/query` (LLM-bound) | 2s | 8s |
| `GET /audit/export.csv?limit=10k` | 800ms | 3s |

### Soft budgets (warn at p50)

| Endpoint | Soft p50 |
|---|---|
| Any `GET` | 100ms |
| Any `POST` non-LLM | 200ms |
| Any auth callback (Supabase round-trip) | 400ms |

Failing the hard p99 is a sev-2 incident; ops investigates within
2 hours. Failing the soft p99 sustained for >1 hour → review next
sprint.

### Profiling

Sentry profiling is opt-in via `SENTRY_PROFILES_SAMPLE_RATE`
(default 0). Bump to `0.3` for the duration of an investigation,
then return to 0 — profiling has measurable CPU overhead.

### Benchmark suite (manual)

```bash
make perf-baseline   # runs 30s soak against /me/orgs + /projects + /my-work
make perf-llm        # runs 5x codeguard scan + 5x drawbridge query, reports p50/p95
```

Both targets write to `apps/api/perf_results/{date}.json` for trend
tracking. Run before + after any framework upgrade (FastAPI, SQLAlchemy).

---

## 4. Frontend perf

### Bundle size budget

| Route | Budget (gzip) | Current |
|---|---|---|
| `/login` | 80 KB | 64 KB |
| `/` (marketing) | 100 KB | 78 KB |
| `/pulse/[id]/dashboard` | 250 KB | 218 KB |
| `/schedule/[id]` (Gantt) | 280 KB | 232 KB |

Check with `npm run analyze` (lazy-loaded Next bundle analyzer).

### TTFB

Vercel measures TTFB at edge. Target:
* `/login`, `/`, `/pricing` — static (or close to): <100ms p95.
* `(dashboard)/*` — dynamic SSR with auth check: <400ms p95.

If `(dashboard)/*` TTFB rises, suspect:
1. Supabase auth lookup slowness (Singapore region health).
2. `/me/orgs` API hit during layout render (now cached, but verify
   cache hit-rate in Redis metrics).

### Service worker caching

The PWA service worker (`apps/web/public/sw.js`) caches:
* Static assets (`/_next/static/*`, `/icons/*`) — cache-first.
* Offline shell (`/offline`, `/manifest.webmanifest`) — pre-cached
  on install.

API responses are never cached by the SW — auth-sensitive + freshness
matters. Cache invalidation on deploy is automatic via `SW_VERSION`
bump in sw.js.

---

## 5. Operating signals

Watch in Sentry / Better Stack:

* **Cache hit rate** — `/metrics` exposes `aec_cache_hits_total` and
  `aec_cache_misses_total`. Target hit rate ≥70% on `/me/orgs`.
* **DB connection saturation** — `pg_stat_activity` row count vs
  pool max. Alert at >80%.
* **Slow query log** — Sentry "Slow Query" issues. Triaged weekly.
* **Worker queue depth** — Prometheus `aec_arq_queued_jobs`. Alert
  at >100 sustained 10 min (worker can't keep up).

Dashboards live at the Grafana Cloud workspace (see
`deploy/OBSERVABILITY.md` §3).
