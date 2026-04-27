# Scraper Drift Monitoring

The price-scraper framework writes one telemetry row per invocation to
`scraper_runs` so ops can spot when a provincial DOC site quietly
renames materials, changes its publication cadence, or flat-out goes
offline. Drift is the early-warning signal for "our normaliser rules
need updating before the next month's bulletin."

This doc covers what's stored, where the threshold lives, the admin
endpoint, and the dashboard panel.

---

## 1. What's stored

Every call to `services.price_scrapers.run_scraper(...)` writes a row
via `_persist_run` (best-effort — a DB outage is logged but never fails
the scrape). Schema in migration `0012_scraper_runs.py`, model in
`apps/api/models/core.py::ScraperRun`:

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | server-default `gen_random_uuid()` |
| `slug` | text | scraper slug (`hanoi`, `hcmc`, …) |
| `started_at` | timestamptz | wall clock at run start |
| `finished_at` | timestamptz | when summary was assembled |
| `ok` | bool | True iff `scrape()` returned without raising |
| `error` | text | str(exc) when `ok=false`, else null |
| `scraped` | int | rows the scraper produced |
| `matched` | int | rows the normaliser matched a rule for |
| `unmatched` | int | rows that didn't match any rule |
| `written` | int | rows the writer upserted into `material_prices` |
| `rule_hits` | jsonb | `{material_code: count}` — pre-zero for ALL codes |
| `unmatched_sample` | jsonb | up to 25 distinct `raw_name`s that didn't match |

**Important**: `rule_hits` pre-populates every `material_code` known to
the normaliser to zero. A code that previously fired and now hits zero
is the strongest drift signal we have — the rule has gone dark on this
province. A naive "only present codes that fired" map would lose that
signal.

The table has no `organization_id` and no RLS — global ops data.
`AdminSessionFactory` is the right factory for both writes and reads;
the `aec_app` runtime role gets DML grants automatically via
`ALTER DEFAULT PRIVILEGES` from `0010_app_role.py`.

Index: `(slug, started_at DESC)` covers the common admin query
("last N runs for slug X").

---

## 2. Drift threshold

`services.price_scrapers.__init__._DRIFT_THRESHOLD = 0.30` — at >30%
unmatched ratio we log:

```
WARNING scraper.drift[<slug>]: 4/5 (80%) unmatched — rules may need updating;
                              sample names: ['Đèn LED Philips A19', ...]
```

The threshold is a calibration of "noticeably worse than typical (~5–
15%) but not so tight it cries wolf on a freshly-added province whose
first scrape predates rule tuning." Tune downward once the baseline
ratio across 60+ provinces stabilises.

---

## 3. Reading the data

### Admin API

```
GET /api/v1/admin/scraper-runs?slug=<optional>&limit=<1..200, default 20>
```

- Gated by `require_role("admin")` — non-admins get 403.
- Reads via `AdminSessionFactory`.
- Returns `ScraperRunOut[]` ordered by `started_at DESC`.
- Limit > 200 → 422 (protect the index from a runaway page).

### Dashboard panel

`<ScraperRunsPanel>` in `packages/ui/costpulse/`. Mounted on the prices
page (`/costpulse/prices`) below the price-history view, gated by
`session.orgs[].role === "admin"`.

The panel surfaces three things ops actually look at:

1. **Status badge per row**: 🟢 OK / 🟡 Drift (above threshold) / 🔴 Failed.
   Drift threshold mirrors the API constant — both sides know that 30%
   is the line.
2. **Counts header**: `N ok · N failed · N drifting`.
3. **Sample unmatched names** for drifting rows — the actual material
   descriptions that didn't normalise. That's the input ops need to
   write a new regex rule.

The hook is `useScraperRuns({ slug, limit, refetchIntervalMs })` in
`apps/web/hooks/admin/useScraperRuns.ts`. `refetchIntervalMs` is opt-in
— callers can flip on live monitoring during an ops session.

### Direct SQL

For deeper queries (rule-hits trend across runs, top unmatched names
across provinces) just query the table directly:

```sql
-- "Which scrapers have drifted the most over the last 30 days?"
SELECT slug,
       avg(unmatched::float / NULLIF(scraped, 0)) AS avg_drift,
       count(*) AS runs
FROM scraper_runs
WHERE started_at > now() - interval '30 days' AND ok
GROUP BY slug
HAVING count(*) >= 2
ORDER BY avg_drift DESC NULLS LAST
LIMIT 20;
```

```sql
-- "Which material_codes have lost coverage on a given province?"
SELECT key,
       sum((value::int)) AS hits,
       count(*) AS runs_in_window
FROM scraper_runs,
     jsonb_each_text(rule_hits)
WHERE slug = 'hanoi'
  AND started_at > now() - interval '6 months'
GROUP BY key
ORDER BY hits ASC, runs_in_window DESC;
```

---

## 4. What to do when drift fires

1. Run the admin endpoint or panel to see `unmatched_sample`.
2. Cross-reference with the live bulletin (the `source_url` from the
   underlying `material_prices` row, or just visit the province's
   listing page).
3. Update `services.price_scrapers.normalizer._RULES` — add a regex,
   tighten an existing one, or accept that the line is intentionally
   ignored (e.g. `Lao động phổ thông` is labour, not a material).
4. Re-deploy. The next monthly cron run will produce a fresh
   `scraper_runs` row whose `rule_hits` reflects the new rule
   coverage; drift should drop back below 30%.

---

## 5. Tests

- `apps/api/tests/test_price_scrapers.py` covers:
  - Drift WARN fires above threshold; doesn't fire below.
  - `ScraperRun` row written on success, on `ScrapeError`, and silently
    on telemetry-DB outage.
  - `unmatched_sample` is distinct + capped at 25.
  - `rule_hits` pre-populates every code to zero.
- `apps/api/tests/test_admin_router.py` covers:
  - Happy path returns rows verbatim.
  - `slug` filter reaches the SQL WHERE.
  - `limit > 200` rejected with 422.
  - Non-admin role → 403.
