# Multi-region active-passive failover runbook

Available on the **Enterprise** plan. Single-region deploys (Starter,
Pro) ride on Supabase's built-in HA inside Singapore — adequate for
99.5% uptime, but a Singapore-wide outage blacks them out.

The Enterprise topology adds:
  * **Read replica** in AWS Tokyo (or AWS Mumbai for India customers)
  * Pre-staged Vercel + Railway clones in the secondary region
  * Documented failover procedure (RTO ≤ 30 min, RPO ≤ 1 min)
  * Quarterly drill checklist

This doc is the operations runbook the IT lead at a customer site
(or our internal ops) follows when Singapore goes dark.

---

## 1. Topology

```
                    Internet
                       │
              ┌────────┴────────┐
              │   Cloudflare    │   ← DNS + global health check
              │   geo-failover  │
              └────────┬────────┘
                       │
       ┌───────────────┴───────────────┐
       ▼ (primary, normal)             ▼ (passive, hot-standby)
┌────────────────┐               ┌────────────────┐
│ Singapore      │               │ Tokyo          │
│                │               │                │
│ Supabase PROD  │── replication ▶ Supabase READ  │
│ Railway api    │     stream      │ Railway api  │
│ Railway worker │                 │ Railway worker│
│ Upstash Redis  │     SYNC ◀──────│ Upstash Redis│
│ MinIO          │    on-demand    │ MinIO        │
└────────────────┘                 └────────────────┘
```

**Key invariants:**

1. **Single writer at all times**. The Tokyo replica is read-only
   under normal operation. A failover promotes it to primary; we
   never have two writeable regions simultaneously (would invent
   split-brain).
2. **Sub-second replication lag**. Supabase logical replication
   pushes WAL records to Tokyo. Lag is monitored via the `pg_stat_
   replication` view exposed at `/metrics`.
3. **Redis is regional, not replicated**. Job queue state is
   ephemeral — losing it costs at most one cron-cycle of work.
   Drawbridge ingest jobs in-flight at failover time are lost +
   user re-uploads; we accept this trade-off for operational
   simplicity.

---

## 2. Pre-failover monitoring

### 2a. Health signals

The CI cron `monitoring/supabase-replication-lag` (runs every 5 min)
checks:
  * `pg_replication_slots.confirmed_flush_lsn` is within 16 MB of
    primary's `pg_current_wal_lsn`. Alert at >100 MB; page at >1 GB.
  * `pg_stat_replication.replay_lag` < 10 seconds. Alert at >60s.

Sentry alerts route to **#aec-platform-ops** Slack with sev=major
if either threshold trips. Sustained 30 min of alert → start the
failover decision tree.

### 2b. Failover decision tree

```
                    Singapore reachable from Cloudflare?
                    /                                  \
                  YES                                  NO
                   │                                    │
       Database accepting writes?                 Initiate failover §3
         /             \
       YES              NO
        │                │
   No action        Supabase incident page →
                    estimated recovery > 15 min? →
                          /          \
                         NO           YES
                          │            │
                       Wait        Initiate failover §3
```

The "wait" branch is critical — many Supabase incidents resolve
within 15 min via their own failover-within-Singapore. We don't
want to flip regions for a 3-min hiccup.

---

## 3. Failover procedure (RTO ≤ 30 min)

> **Authorisation required** — only an Engineering Director can call
> this. Failover is destructive on the primary side (it gets demoted;
> any in-flight writes are lost). Record the call in `#aec-platform-incidents`.

### Step 1 — Pause all writes (2 min)

```bash
# From any operator's laptop with admin credentials
export AEC_OPS_TOKEN=...
curl -X POST https://api.aec-platform.vn/api/v1/admin/ops/freeze \
  -H "Authorization: Bearer $AEC_OPS_TOKEN"
```

This sets a global flag in Redis (`ops:freeze=1`) that the API checks
on every write request. Writes get a 503 "maintenance in progress"
with a retry-after of 30 min. Reads still work.

### Step 2 — Wait for replication to catch up (≤ 2 min)

```bash
# Check Tokyo replica's lag vs Singapore primary
curl https://api-tokyo.aec-platform.vn/_health/replication
# Wait until "replay_lag_seconds < 1"
```

If primary is fully offline (Singapore down), skip this — replication
has been catching up async + Tokyo is as fresh as it can be. Note
the lag in the incident log for RPO measurement.

### Step 3 — Promote Tokyo replica (5 min)

```bash
# Supabase dashboard → Tokyo project → Settings → Database → Promote
# OR via API:
curl -X POST https://api.supabase.com/v1/projects/$TOKYO_PROJECT_REF/promote \
  -H "Authorization: Bearer $SUPABASE_PAT"
```

After promotion:
* Tokyo Postgres accepts writes.
* Replication stream is severed (Singapore can no longer push WAL
  even after coming back up).

### Step 4 — Cut DNS over to Tokyo (5 min, automatic via Cloudflare)

Cloudflare's health-check probe detects Singapore primary unreachable
within 60s and automatically routes `api.aec-platform.vn` to the
Tokyo pool. If automation fails, manual override:

```bash
# Cloudflare dashboard → Load Balancers → aec-api → Origins →
# disable Singapore-1, enable Tokyo-1
```

Vercel: web frontend is multi-region by default — no action needed.

### Step 5 — Bring up Tokyo Railway services (5 min)

Tokyo Railway services run in **idle** mode normally (1 replica, sleeping):

```bash
railway environment use tokyo
railway service scale aec-platform-api --replicas 3
railway service scale aec-platform-worker --replicas 2
# Verify they all bind to the promoted DB:
railway run --service aec-platform-api -- python -c "
from db.session import engine
import asyncio
async def check():
    async with engine.connect() as c:
        print(await c.scalar('SELECT pg_is_in_recovery()'))
asyncio.run(check())
"
# Expect: False (no longer a recovering replica)
```

### Step 6 — Unfreeze writes (1 min)

```bash
curl -X POST https://api.aec-platform.vn/api/v1/admin/ops/unfreeze \
  -H "Authorization: Bearer $AEC_OPS_TOKEN"
```

### Step 7 — Smoke test (5 min)

Run the smoke suite against the new primary:

```bash
SMOKE_BASE_URL=https://api.aec-platform.vn make smoke
```

Suite covers:
* Login (Supabase auth in Tokyo)
* Read a project, list tasks
* Create a task → read it back (write path)
* Trigger one CodeGuard scan (LLM + DB)
* Enqueue + complete a drawbridge ingest job (Redis + worker)

### Step 8 — Communicate (5 min)

* Status page: post "Resolved" with the timeline.
* Customer success: email enterprise customers with the RTO/RPO
  actual numbers from this incident vs. the SLA.
* Internal: incident review scheduled within 48h.

---

## 4. Failback procedure (when Singapore recovers)

**Not urgent.** Tokyo can run as primary indefinitely. Failback
should be scheduled during a low-traffic window (Sunday 2am ICT)
to minimise customer impact.

### Step F1 — Rebuild Singapore as replica

```bash
# Singapore Supabase → Settings → Database → "Restore from backup"
# Pick the latest backup taken after the failover (≤ 1 hour old).
# Then re-establish replication from Tokyo → Singapore.
```

### Step F2 — Wait for catch-up

Same monitoring as §2a, but in reverse. Catch-up typically takes
30-60 min depending on data drift.

### Step F3 — Reverse promotion

Repeat §3 in reverse: freeze, wait, promote Singapore, cut DNS,
scale Tokyo down, unfreeze.

---

## 5. Quarterly drill

Run a real drill once per quarter to keep the runbook current. The
drill is on a **staging environment**, not production.

```bash
# Schedule via the drill template (already in calendar)
make drill-failover ENV=staging
```

The Makefile target:
1. Spins up a parallel staging environment in Tokyo.
2. Runs §3 steps with a stopwatch.
3. Records actual RTO + lag in `docs/failover-drills/{date}.md`.

Goal: keep actual RTO under 30 min on every drill. If a drill exceeds
40 min, file a defect and re-run the next month.

---

## 6. Cost

The cold-standby Tokyo infra costs roughly:
* Supabase read replica: ~$60/month
* Cloudflare Load Balancer with health check: ~$5/month
* Idle Railway services (1 api + 1 worker, ~256 MB each): ~$10/month
* Upstash Redis Tokyo: ~$10/month

≈ **$85/month** baseline + spike during failover when scaled. Bundled
into the Enterprise SLA fee — never charged separately.

---

## 7. Out of scope (today)

* **Active-active** — two regions taking writes simultaneously. Needs
  conflict-free CRDTs or a Spanner-style sync layer. Out of reach for
  our scale; revisit at 1000+ customer orgs.
* **Multi-continent failover** (e.g. Singapore → AWS Frankfurt). Latency
  to VN users from Europe is 250+ ms — would hurt UX more than the
  outage it's protecting against. Tokyo is the only reasonable secondary
  for SE Asia traffic.
* **MinIO replication**. Drawings are large + write-rare; we use S3
  versioning + nightly cross-region copy instead of synchronous
  replication. Failover loses up to 24h of drawing uploads — documented
  in SLA fine print.
