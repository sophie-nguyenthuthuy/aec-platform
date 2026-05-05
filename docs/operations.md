# Operations Runbook

Day-to-day ops for the AEC platform. Anything tagged with **GATE** needs an
on-call engineer's eyes before running it in production. Anything tagged
with **SAFE** is idempotent and can be re-run after an interrupted attempt.

For the architectural shape behind these procedures, see
`docs/architecture.md`. For module-specific runbooks, see
`docs/codeguard.md`, `docs/scraper-drift-monitoring.md`, etc.

---

## Backfills

Backfills are **one-shot CLIs** you run against a writable DB after
a feature lands that needs to fill in state on rows created **before**
the feature existed. They live in `apps/api/scripts/` and are wired into
the root `Makefile` so ops doesn't need to remember the `PYTHONPATH`
incantation.

All backfills:

- Read `DATABASE_URL` from the environment (same async DSN the API uses).
- Take `--dry-run` to count what they'd touch without writing.
- Take `--org-id <uuid>` to scope to a single tenant.
- Are **SAFE** to re-run — the underlying upsert / sync helpers
  short-circuit on rows that already have the desired state, so an
  interrupted run picks up cleanly.
- Commit per-row (or per-batch) — Ctrl-C leaves the partial result
  committed, so no rollback is needed before re-running.

Forward extra flags through `ARGS=`:

```bash
make backfill-rfi-embeddings ARGS="--dry-run -v"
make backfill-dailylog ARGS="--org-id 00000000-0000-0000-0000-000000000000"
```

### `make backfill-rfi-embeddings`

**What it does**: walks every row in `rfis` ordered by `created_at` and
calls `ml.pipelines.rfi.upsert_rfi_embedding(...)` for each. Populates
the `rfi_embeddings` table that powers
`/api/v1/submittals/rfis/{id}/similar` and the `/draft` endpoint's
ground-truth precedent search.

**When to run**:

- After applying the migration that added `rfi_embeddings` (any tenant
  that had RFIs before that point has zero embedded RFIs and similarity
  search returns nothing).
- After upgrading the `OPENAI_EMBEDDING_MODEL` env var — re-embedding
  refreshes `rfi_embeddings.model_version` so the partial index used by
  the pipeline filters out stale vectors.
- After a partial restore that left some rfis without embeddings.

**Required env**:

- `DATABASE_URL` — async DSN to a writable DB at migration head.
- `OPENAI_API_KEY` — without it, the pipeline emits zero vectors and
  the script will run to completion but the search becomes useless.
  **GATE** — refuse to run in production without this.

**Cost**: roughly 1¢ per 1k RFIs at current `text-embedding-3-large`
pricing. A 50k-RFI tenant runs ~50¢; a 500k-RFI multi-tenant cluster
runs ~$5 end-to-end.

**Runtime**: dominated by OpenAI's embed-batch latency — about
~50 RFIs/sec single-threaded.

**Rollback**: not needed. The upsert is keyed on `rfi_id`; if you want
to drop the embeddings entirely, `TRUNCATE rfi_embeddings;` is safe and
the pipeline auto-re-embeds new RFIs at create/update time.

### `make backfill-dailylog`

**What it does**: walks every row in `safety_incidents WHERE project_id
IS NOT NULL` and calls `services.dailylog_sync.sync_incident_to_dailylog`
for each. Mirrors SiteEye safety incidents into the DailyLog
`observations` table so a daily field report shows the safety items that
were already captured by the SiteEye pipeline.

**When to run**:

- After enabling the dailylog↔siteeye sync feature on a tenant that's
  been using SiteEye for a while — every existing incident needs a
  mirror observation row created retroactively.
- After a 3rd-party safety-system import that bulk-loaded historical
  incidents into `safety_incidents`.

**Required env**:

- `DATABASE_URL` — async DSN at migration head.

**Cost**: free — no external API calls, just DB reads + writes.

**Runtime**: about ~200 incidents/sec single-threaded; bound by the
per-incident commit (intentional — see "interrupted runs" below).

**Idempotency**: an incident whose mirror observation already exists
(linked via `observations.related_safety_incident_id`) is skipped.
Re-running on a fully-mirrored tenant is a fast no-op.

**Interrupted runs**: each incident commits independently, so a Ctrl-C
mid-script leaves every successfully-mirrored incident intact. The next
run picks up at whatever incident wasn't mirrored yet.

**Rollback**: filter for the audit window and delete:

```sql
DELETE FROM observations
 WHERE related_safety_incident_id IS NOT NULL
   AND created_at >= '<backfill start ts>';
```

This is **GATE** — make sure no human has manually edited a mirrored
observation in that window before running it.

---

## Codeguard quotas

The CLI lives in `scripts/codeguard_quotas.py`. See `docs/codeguard.md`
for the per-org-quota model. Key commands:

```bash
# Read a tenant's quota + current-month usage.
python scripts/codeguard_quotas.py get --org-id <uuid>

# Set a monthly cap. Either flag can be omitted to leave that
# dimension unlimited; both omitted is a usage error.
python scripts/codeguard_quotas.py set --org-id <uuid> \
    --input-limit 10000000 --output-limit 2000000

# List all orgs sorted by binding-percent descending; pass --over-pct
# to show only orgs above a threshold.
python scripts/codeguard_quotas.py list --over-pct 80
```

`set` writes a row to `codeguard_quota_audit_log` in the same
transaction. The `actor` column defaults to `$USER` but accepts
`--actor` for service-account scripts. **SAFE** — the upsert is keyed
on `organization_id` and the audit row captures the diff.

---

## Pulse client report

Generated end-to-end by:

1. `routers/pulse._aggregate_report_inputs(...)` — fans out 13 SQL
   queries against the project to populate the LLM's context.
2. `ml.pipelines.pulse.generate_client_report(...)` — narrates the data
   into `ClientReportContent` via Anthropic.
3. `ml.pipelines.pulse.render_report_html(...)` + `render_report_pdf(...)`
   — branded HTML, optional WeasyPrint→PDF.

If WeasyPrint isn't installed, the route catches `PDFRendererUnavailable`
and stores `pdf_url=None`. The frontend gracefully falls back to the
HTML preview. Install WeasyPrint + native deps in the worker image:

```dockerfile
RUN apt-get install -y libpango-1.0-0 libcairo2 libgdk-pixbuf-2.0-0
RUN pip install weasyprint
```

Verify with `pytest apps/ml/tests/test_pulse_client_report.py -v` —
the PDF test skips when WeasyPrint is missing, so a green run with
`SKIPPED [100%]` for `test_render_report_pdf_either_renders_or_raises_unavailable`
means PDF rendering is **NOT** wired in your environment.

---

## Audit events

The `audit_events` table is the cross-module governance trail. Every
governance-bearing transition (handover delivery, CO approve/reject,
punch sign-off, submittal review verdict) writes one row in the same
transaction as the underlying mutation. See
`apps/api/services/audit.py::AuditAction` for the closed action set.

**Read paths**:

- `/api/v1/audit/events` — paginated list (admin-only).
- `/api/v1/audit/events?resource_type=...&resource_id=...` —
  per-resource filter, drives the `ResourceAuditPanel` on project
  detail.

**Operational notes**:

- The table is **append-only**. Don't DELETE rows; if you need to
  redact a value, UPDATE the `before` / `after` JSONB to a marker
  like `{"redacted": true}` and add a fresh audit row recording the
  redaction.
- Webhook outbox: every `audit.record(...)` call also enqueues a
  webhook delivery via `services.webhooks.enqueue_event` in the same
  transaction. A rolled-back handler rolls back both — customers
  never get notified about a write that didn't commit.

---

## Health probes

- `GET /health` — process liveness. Cheap, no DB/Redis hits. Used by
  the LB's "is the pod running" check.
- `GET /health/ready` — DB + Redis reachability. 503 when degraded so
  the LB pulls the pod out of rotation. Each probe has a 1s timeout;
  per-dep status is reported in the response body for fast triage.
- `GET /metrics` — Prometheus exposition. The `arq_queue_depth` gauge
  is sampled lazily on each scrape (no separate cron).

The metrics endpoint is **public by convention** — scrapers run without
auth. Restrict it at the LB / network level if your deployment exposes
the API to the internet.

---

## Things you should NOT do without an explicit incident

- `git push --force` to `main` — breaks every other engineer's checkout
  and rewrites the audit trail of what shipped when. Use `git revert`
  instead.
- `TRUNCATE audit_events` / `TRUNCATE codeguard_quota_audit_log` —
  these tables are evidence under VN personal-data law. If you need to
  reset them in a non-prod environment, do it via the migration runner
  with a comment in the migration explaining why.
- Run a backfill against production without `--dry-run` first —
  always pin the row count before committing the writes.
- Skip the pre-commit hooks (`--no-verify`) — they catch ruff drift,
  trailing whitespace, and accidentally-committed secrets. The one
  exception is when the hook itself is in a conflict-rollback loop on
  a large staged set; in that case, run `ruff check --fix` + `ruff
  format` manually first, then commit normally.
