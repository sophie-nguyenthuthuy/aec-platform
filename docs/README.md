# Platform Docs

Per-module deep-dives. Read whichever's relevant; no recommended order.

| Doc | What it covers |
|---|---|
| [`codeguard.md`](./codeguard.md) | RAG-backed compliance assistant (QCVN/TCVN). |
| [`costpulse-boq-io.md`](./costpulse-boq-io.md) | BOQ Excel/PDF import/export — column detection, decimal coercion, format adapters. |
| [`public-rfq-portal.md`](./public-rfq-portal.md) | Supplier-facing RFQ-response page — JWT-token auth, rate limiter, i18n, dashboard panel. |
| [`scraper-drift-monitoring.md`](./scraper-drift-monitoring.md) | `scraper_runs` telemetry — admin endpoint, drift threshold, dashboard panel, ops queries. |
| [`testing.md`](./testing.md) | How the test suite is organised, integration-test gating, RLS coverage sweep. |

## Cross-module conventions

A few platform-wide invariants the per-module docs assume:

- **Two DB factories**, both in `db/session.py`:
  - `SessionFactory` — `aec_app` role, NOBYPASSRLS. Default for request handlers.
  - `AdminSessionFactory` — `aec` role, BYPASSRLS. For cross-tenant batch
    jobs and global ops tables (`scraper_runs`, identity primitives).
  - The split + grants live in migration `0010_app_role.py`.
- **RLS sweep**: `apps/api/tests/test_rls_coverage.py` runs against a live
  DB and asserts every `public.*` table with an `organization_id` column
  has RLS enabled and at least one policy attached. Allowlist is small
  and each entry has a justification.
- **Observability**: `core/observability.py::setup_observability(app)` wires
  request-ID middleware, structured logging (json/pretty), Sentry init
  (no-op without DSN), and SQLAlchemy slow-query detection on both
  engines. Configurable via `LOG_FORMAT`, `LOG_LEVEL`, `SENTRY_DSN`,
  `SLOW_QUERY_MS` env vars.
- **Public endpoints** sit at `/api/v1/public/...`. The path prefix is the
  visual marker that `require_auth` is intentionally bypassed; the token
  in the request is the entire authn surface.
