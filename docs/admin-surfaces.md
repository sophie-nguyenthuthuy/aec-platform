# Platform admin surfaces — index

Single source of truth for "what dashboards do I have, and where's
the runbook?". Everything here is admin-role-gated server-side; the
landing page at `/admin` is the navigation hub.

If a dashboard is missing from this index, either:
- It's been added without updating this doc (please update — see
  the contribution checklist at the bottom).
- It's been retired (please remove the entry).

The state of "every dashboard tile is on `/admin`" is itself pinned
by `apps/web/app/(dashboard)/admin/__tests__/page.test.tsx`.

---

## Triage dashboards

These are the surfaces ops opens **during an incident**. Each card
on the landing page links to one of these. The runbook column is
what to read when the dashboard turns red.

| Dashboard                  | URL                            | Runbook                                                      | Backend pin                                          | Frontend pin                                                   |
| -------------------------- | ------------------------------ | ------------------------------------------------------------ | ---------------------------------------------------- | -------------------------------------------------------------- |
| API key usage              | `/admin/api-usage`             | _(no runbook yet — usage telemetry, no escalation path)_     | _(none)_                                             | _(none)_                                                       |
| Webhook deliveries         | `/admin/webhook-deliveries`    | [`runbook-webhook-deliveries.md`](runbook-webhook-deliveries.md) | `tests/test_webhook_deliveries_admin_surface_pin.py` | `hooks/admin/__tests__/useWebhookDeliveriesAdmin.test.tsx`    |
| Webhook delivery detail    | `/admin/webhook-deliveries/[id]` | (same as parent)                                            | (same as parent — detail endpoint pinned in the same file) | (same as parent — detail hook pinned in the same file)    |
| Slack deliveries           | `/admin/slack-deliveries`      | [`runbook-slack-deliveries.md`](runbook-slack-deliveries.md) | `tests/test_slack_deliveries_surface_pin.py` + `tests/test_slack_render_contract_pin.py` | `hooks/admin/__tests__/useSlackDeliveries.test.tsx`           |
| Cron jobs                  | `/admin/crons`                 | [`runbook-cron-admin.md`](runbook-cron-admin.md) + [`runbook-cron-watchdog.md`](runbook-cron-watchdog.md) | `tests/test_cron_admin_surface_pin.py` + `tests/test_cron_telemetry_behaviour_pin.py` + `tests/test_cron_alerts_watchdog_pin.py` | `hooks/admin/__tests__/useCrons.test.tsx`                     |
| Cron drilldown (per-cron)  | `/admin/crons/[cron_name]`     | (same as parent)                                             | (same as parent — `/runs` endpoint pinned)           | `hooks/admin/__tests__/useCronRuns.test.tsx`                  |

## Configuration / management dashboards

These are the surfaces ops opens **between incidents** to tune
platform-wide behaviour.

| Dashboard                  | URL                            | Runbook                                                      | Backend pin                                          | Frontend pin                                                   |
| -------------------------- | ------------------------------ | ------------------------------------------------------------ | ---------------------------------------------------- | -------------------------------------------------------------- |
| Price scrapers             | `/admin/scrapers`              | [`scraper-drift-monitoring.md`](scraper-drift-monitoring.md) | `tests/test_scraper_orchestration_constants_pin.py` | `hooks/admin/__tests__/useScraperRuns.test.tsx` (sparkline tests in `_components/__tests__/Sparkline.test.tsx`) |
| Normaliser rules           | `/admin/normalizer-rules`      | _(no runbook yet — referenced from scraper-drift runbook)_   | _(none)_                                             | `hooks/admin/__tests__/useNormalizerRules.test.tsx`           |

---

## How the dashboards talk to each other

```
        +------------------+
        |   /admin (hub)   |
        +--------+---------+
                 |
   +-------------+-------------+----------------+--------------+
   |             |             |                |              |
   v             v             v                v              v
api-usage   webhook-     slack-           crons          scrapers
            deliveries   deliveries         |             |
                |                         crons/[name]   normalizer-rules
                v
            webhook-
            deliveries/[id]
```

The admin landing page is the only navigation affordance for these
sub-pages — there's no global menu entry. Ops bookmarks `/admin`
and discovers the rest from there.

---

## Cross-cutting infrastructure pins

These pin the primitives that every admin surface depends on. A
regression here breaks ALL admin pages simultaneously, so the
tripwires are especially valuable.

| Surface                                     | Pin file                                                  | What it guards                                                                                            |
| ------------------------------------------- | --------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| Response envelope (`core.envelope`)         | `tests/test_envelope_shape_pin.py`                        | `ok()`/`paginated()`/`Envelope[T]` shape, error handler accepts `details_url` deep-link                  |
| Auth dependency (`middleware.auth`)         | `tests/test_require_role_pin.py`                          | `require_role`, `AuthContext` field set, frozen-dataclass posture, 403-on-mismatch                        |
| API-key auth (`middleware.api_key_auth`)    | `tests/test_api_key_auth_contract_pin.py`                 | `aec_` prefix dispatch, role synthesis, scope/project gates                                              |
| API-key service (`services.api_keys`)       | `tests/test_api_keys_service_pin.py`                      | `KEY_PREFIX`, hash algorithm, scope/project access semantics, `record_call` swallow-on-failure           |
| Audit endpoint (`routers/audit.py`)         | `tests/test_audit_router_surface_pin.py`                  | Path, admin gate, filter param shape, `actor_kind` regex, pagination bounds, organization_id RLS         |
| Audit writer (`services.audit.record`)      | `tests/test_audit_record_signature_pin.py` + `tests/test_audit_record_actor_routing_pin.py` | Signature, actor-routing branch (user vs api_key), webhook coupling, default-empty diffs                  |
| Slack send (`services.slack`)               | `tests/test_slack_render_contract_pin.py`                 | `send_slack` shape, `render_slack_drift_alert` `(text, blocks)` tuple, `slack_not_configured` reason     |
| Mailer (`services.mailer`)                  | `tests/test_mailer_contract_pin.py`                       | `send_mail` shape, `Delivery` TypedDict, `smtp_not_configured` skipped path, never-raises invariant       |
| DB session factories (`db.session`)         | `tests/test_db_session_factories_pin.py`                  | `SessionFactory` (RLS-scoped) ≠ `AdminSessionFactory` (BYPASSRLS), `TenantAwareSession` uses RLS factory |
| Idempotency (`services.idempotency`)        | `tests/test_idempotency_contract_pin.py`                  | Body canonicalisation, sha256-hex hashing, `FOR UPDATE` serialisation, `IdempotencyResult` discriminator |
| Activity stream (`services.activity_stream`) | `tests/test_activity_stream_contract_pin.py`             | Ticket TTL + key prefix, `_channel_name` org-wide-vs-per-project, atomic GETDEL replay defence            |
| Rate limiter (`services.rate_limit`)        | `tests/test_rate_limit_contract_pin.py`                   | `_hash_key` no-leak property, bucket capacity clamp, deploy-time-rebuild on capacity/rate change         |
| Webhook outbox state machine                | `tests/test_webhook_outbox_state_machine_pin.py` + `tests/test_webhook_delivery_headers_pin.py` + `tests/test_webhooks_backoff_schedule.py` | Status literals, ORM column shape, HMAC + timestamp headers, retry budget |

---

## Contribution checklist for new admin surfaces

When adding a new `/admin/X` page:

1. **Backend router** — new file under `apps/api/routers/X_admin.py`
   (do NOT append to `routers/admin.py`; that file is on the
   upstream-revert pattern's known target list). Wire in `main.py`
   with a single-line `include_router(...)` call.

2. **Schema file** — new file under `apps/api/schemas/X.py` (same
   revert-avoidance rationale as the router file).

3. **Frontend hook** — new file under `apps/web/hooks/admin/useX.ts`,
   re-exported from `apps/web/hooks/admin/index.ts`.

4. **Frontend page** — new file under
   `apps/web/app/(dashboard)/admin/X/page.tsx`.

5. **Landing tile** — add an entry to the `ADMIN_PAGES` array in
   `apps/web/app/(dashboard)/admin/page.tsx` AND bump the
   `EXPECTED_TILES` count in
   `apps/web/app/(dashboard)/admin/__tests__/page.test.tsx`.

6. **i18n keys** — add an `admin_X` namespace to BOTH
   `apps/web/i18n/messages/en.json` and `vi.json`. The parity test
   in `apps/web/i18n/__tests__/parity.test.ts` enforces both locales
   stay in sync.

7. **Backend pin** — new file under
   `apps/api/tests/test_X_admin_surface_pin.py` covering router
   path, role gate, schema field set, source-grep for any
   security-critical literals.

8. **Frontend pin** — new file under
   `apps/web/hooks/admin/__tests__/useX.test.tsx` covering URL,
   tri-state filter handling, envelope unwrap, query-key
   namespacing.

9. **Runbook** — new file under `docs/runbook-X.md` covering "what
   does red mean", common error decoder table, escalation paths,
   related code, pin tests.

10. **Update this index** — add a row to the appropriate table
    above (triage / configuration) AND add the pin files to the
    cross-cutting section if any new infra primitives were
    introduced.

If steps 1-9 land but step 10 doesn't, the dashboard works but
nobody finds it during an incident — the index is the discovery
surface for future on-call rotations.
