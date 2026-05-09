# CODEGUARD quotas — operating guide

The codeguard pipeline enforces a per-org monthly token cap on every
LLM-invoking route. This doc bridges "the system is running" and "ops
can answer cap questions without grepping source." It covers the
three pieces an on-call engineer needs at 3am:

1. **What the policy is** — weights per route, threshold tiers, how
   the cap interacts with raw token counts.
2. **How to read the alerts** — what each Prometheus rule means and
   what action it implies.
3. **How to remediate** — CLI subcommands for set / reset / reconcile
   / drill-down, in the order an investigation typically runs them.

Sibling docs:
- `docs/codeguard.md` — the codeguard pipeline itself (retrieval,
  generation, scan flows).
- `docs/codeguard-telemetry.md` — per-LLM-call cost records (the
  data feeding the cap counters).

---

## 1. The weighted-accounting policy

Not every codeguard route is equal-cost. `/scan` reads an entire
project, embeds every file, and runs a multi-pass review — vastly
more compute than `/query`'s single-shot retrieval. Provider-token
counts alone undercharge `/scan` against the org's monthly cap.

The fix is a per-route multiplier applied at recording time. Three
weights are pinned in
`apps/api/services/codeguard_quota_attribution.py` (`ROUTE_WEIGHTS`):

| Route               | Weight | Rationale                                    |
| ------------------- | ------ | -------------------------------------------- |
| `query`             | 1.0×   | Baseline — single-shot retrieval-and-answer. |
| `permit-checklist`  | 2.0×   | Structured output (checklist + rationale).   |
| `scan`              | 5.0×   | Full-project read + multi-pass LLM checks.   |

**What gets scaled:** the recorded counters in `codeguard_org_usage`,
`codeguard_user_usage`, and `codeguard_user_usage_by_route`. The cap
check reads those counters directly, so `/scan` consumes the cap at
5× the raw provider-token rate.

**What does NOT get scaled:** the LLM telemetry log
(`docs/codeguard-telemetry.md`) records raw provider tokens
unweighted — it's the audit trail of what the LLM actually did.

**Common confusion** — an admin getting a 95% threshold email looks
at their raw-token logs and sees 19% of the cap. This is correct: a
heavy `/scan` month at 5× weight pushes the cap-counter percent up
without the raw token count following. The threshold email and the
banner tooltip both carry a one-sentence note explaining this.

To inspect the current policy from the CLI:

```bash
python scripts/codeguard_quotas.py routes
# route_key                  weight
# ---------------------------------
# scan                         5.00
# permit-checklist             2.00
# query                        1.00
```

To bump a weight, edit `ROUTE_WEIGHTS` in the attribution module.
The snapshot test (`tests/test_codeguard_surface_snapshot.py`) pins
`scan ≥ 2.0` so a "weights silently flattened to 1.0" stub gets
caught at PR time.

---

## 2. The threshold tiers

Two notification thresholds, distinct urgency:

- **80%** — yellow, "approaching cap, plan ahead." Email + Slack go
  to the org's `quota_warn` opt-in list.
- **95%** — red, "imminent — next request may 429." Same channels;
  the subject line and banner color escalate.

The threshold check fires AFTER each successful `record_org_usage`,
gated by `codeguard_quota_threshold_notifications` (composite PK on
`org_id+dimension+threshold+period_start`) so a flapping account
that re-records the same month 100 times still gets exactly one
email per (dimension, threshold, period).

To inspect an org's current state:

```bash
python scripts/codeguard_quotas.py get <org-uuid>
```

To find at-risk orgs:

```bash
python scripts/codeguard_quotas.py list --over-pct 80
```

---

## 3. The Prometheus alerts

Three rules in `infra/prometheus/codeguard.alerts.yml`:

### `CodeguardQuotaCheckSlow` (warn)

Fires when the pre-flight cap-check histogram's p99 exceeds 100ms
sustained for 5 minutes. Means the `check_org_quota` SELECT is slow
— usually a missing index after a schema change, or
`codeguard_org_usage` got large enough that the `(org, period)` PK
lookup is no longer cheap.

**Action:** `EXPLAIN ANALYZE` the cap-check query (see
`apps/api/services/codeguard_quotas.py::check_org_quota`). If the
plan shows a Seq Scan, an index is missing.

### `CodeguardQuotaRefusalSpike` (page)

Fires when `codeguard_quota_429_total{limit_kind=…}` increments at
≥10/min sustained for 2 minutes. Means orgs are hitting their caps
faster than usual — either legitimate usage growth or a runaway
client.

**Action:**
1. `quotas list --over-pct 95` to find the affected orgs.
2. `quotas usage-by-route <org>` to see which routes drove the
   spend (heavy `/scan` is the typical culprit).
3. If legitimate growth, raise the cap with `quotas set`. If a
   runaway client, contact the customer.

### `CodeguardQuotaUsageDrift` (warn)

Fires when `codeguard_quota_drift_rows > 0` sustained for 1 hour.
Set by the weekly reconcile cron — counts `(org, period)` rows
where `codeguard_org_usage` totals diverge from
`SUM(codeguard_user_usage)` by more than 1000 tokens.

**Action:**
1. `python scripts/codeguard_quotas.py reconcile` (read-only) to
   see which org/period rows are drifted.
2. Investigate WHY — typical causes:
   - The per-user sidecar write was failing for some requests
     (check `record_user_usage` warning logs).
   - A migration / backfill / reset touched one table without the
     other.
3. Fix forward with `python scripts/codeguard_quotas.py reconcile
   --remediate --confirm`. This realigns `codeguard_org_usage` to
   `SUM(codeguard_user_usage)` and writes a `quota_reconcile`
   audit row per realigned (org, period).

---

## 4. The CLI surface

The script lives at `scripts/codeguard_quotas.py`. Connection comes
from `DATABASE_URL` (asyncpg form) — same env var the API uses, so
running locally hits the same DB the pod reads.

Every subcommand supports `--json` for piping into `jq`:

```bash
python scripts/codeguard_quotas.py --json get <org> | jq .
```

Quick reference:

| Subcommand               | Purpose                                              |
| ------------------------ | ---------------------------------------------------- |
| `set <org> --input-limit N --output-limit N` | Upsert an org's monthly cap (NULL = unlimited per dimension). Writes a `quota_set` audit row. |
| `reset <org> --confirm`  | Zero the org's current-month usage row. Writes a `quota_reset` audit row. |
| `get <org>`              | Show one org's quota + current-month usage with percent-of-cap. |
| `list [--over-pct N]`    | All orgs sorted by binding percent DESC; filter to "at risk." |
| `audit <org> [--since DATE] [--action quota_set\|quota_reset\|quota_reconcile]` | Read the audit log for one org, paginated. |
| `reconcile [--org UUID] [--remediate --confirm]` | Detect (read-only) or fix drift between org-level and per-user totals. |
| `routes`                 | Print `ROUTE_WEIGHTS` as a sorted table. Read-only. |
| `usage-by-route <org>`   | Drill into one org's per-user × per-route spend for the current period. |

The `routes` and `usage-by-route` outputs use vi-VN dot-grouping
(`1.000.000`, not `1,000,000`) — matches the locale convention used
elsewhere in the platform.

---

## 5. The tenant-facing UI

Three pages, all under `/codeguard/quota`:

- **`/codeguard/quota`** — planning surface. Per-dimension progress
  bars (input + output), days-until-reset, 3-month usage history
  strip, and (when capped + has data) a "Top consumers" panel with
  click-to-expand per-route breakdown rows.
- **`/codeguard/quota/audit`** — admin audit log. Filterable by
  action (set/reset/reconcile) and date. CSV export for compliance.
- The dashboard-root layout mounts `<QuotaStatusBanner>` — a yellow
  (≥80%) / red (≥95%) banner that surfaces on every page once the
  org crosses the warn threshold. Hidden under 80% to avoid noise.

The banner carries a small `(?)` info icon with the weighted-
accounting note as a tooltip — same wording as the threshold
email/Slack so an admin reading either doesn't see two
slightly-different explanations.

---

## 6. Retention

`codeguard_quota_audit_log` is in `RETENTION_POLICIES`
(`apps/api/services/retention.py`) with:

- `default_days=730` (2 years) — compliance-relevant, covers
  year-over-year audit comparisons.
- `archive=True` — rows are written to S3 as JSONL before delete,
  so a customer disputing a much older cap change is recoverable.

The retention prune cron runs daily at 03:00 UTC (~10:00 ICT). The
Tier 3 test
(`tests/test_codeguard_quotas_integration.py::test_retention_prune_deletes_old_audit_log_rows_only`)
exercises the prune against a stale row to pin the policy works
end-to-end, not just in the registry.

The other usage tables (`codeguard_org_usage`,
`codeguard_user_usage`, `codeguard_user_usage_by_route`) are NOT in
retention — they accumulate by month and the unbounded growth is
bounded by tenant count × month count, which is small.

---

## 7. Defense against silent revert

The codeguard quota surface has historically been a target for
aggressive linter / reformat passes that drop routes, metric
registrations, or cron entries. Three layers of defense:

1. **Snapshot test** —
   `apps/api/tests/test_codeguard_surface_snapshot.py` pins the
   exact set of routes / metrics / cron jobs / retention policies
   that the system depends on. Failure surfaces as
   "Missing route X" with a clear remediation hint.
2. **Stub-detection** — same file pins that bodies still issue
   expected SQL, not just that names exist (catches the "function
   still there but body hollowed out" failure mode).
3. **Pre-commit + CI** — `.pre-commit-config.yaml` runs the snapshot
   test on every commit attempt that touches a surface file;
   `.github/workflows/ci.yml`'s `codeguard-surface` job runs the
   same test + the Prometheus rule validator on every PR.

When the gate fails, the failure message names exactly which surface
disappeared. Re-add it (the modules are concentrated for this
purpose — see `routers/codeguard_quota.py` and
`services/codeguard_quota_attribution.py` for the at-risk routes
and helpers).
