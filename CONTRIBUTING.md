# Contributing to AEC Platform

Thanks for considering a contribution. This guide is shorter than most because
the tooling does the gatekeeping — you mostly just need to install the
pre-commit hook and let CI tell you when something's off.

## TL;DR

```bash
git clone git@github.com:sophie-nguyenthuthuy/aec-platform.git
cd aec-platform
pnpm install
pip install -r apps/api/requirements-dev.txt
make hooks                                # ← do this once, prevents 90% of CI failures
docker compose up -d                      # Postgres + Redis + Elasticsearch
cd apps/api && alembic upgrade head && cd ../..
```

You're now set up to develop. The pre-commit hook will run on every `git
commit` and block pushes that would fail CI's lint/format gate.

## Workflow

1. **Branch** off `main`. Naming convention: `feat/<short>`, `fix/<short>`,
   `chore/<short>`, `docs/<short>`. The `feat/` prefix is preferred for
   anything that adds user-visible functionality.

2. **Code**. Keep changes scoped. If you find yourself touching three
   modules at once, that's usually two PRs.

3. **Test locally** before pushing — see [Pre-push checklist](#pre-push-checklist)
   below. CI will catch what you miss, but the queue takes 3-5 min and the
   feedback loop is faster on your laptop.

4. **Open a PR** against `main`. Use the auto-generated PR template. Required
   fields: a one-line summary in the title, a "what changed and why" in the
   body. Link any GitHub issue with `Closes #123`.

5. **Wait for green CI**. The five gates are:
   - Pre-commit hooks (ruff + format + file hygiene)
   - Python — API lint + test
   - Node — typecheck + lint + web build + Playwright e2e
   - Terraform — fmt + validate
   - Security — dependency audit (non-blocking)

6. **Merge** via squash. We keep `main` linear; the squash commit message
   should match the PR title.

## Pre-push checklist

The pre-commit hook covers ruff + ruff-format + basic file hygiene. For
everything else, run the relevant lane manually if you've changed code in
its territory:

| Changed | Run |
|---|---|
| Python in `apps/{api,ml,worker}` | `cd apps/api && pytest -q` |
| TypeScript in `apps/web` or `packages/` | `pnpm --filter @aec/web typecheck` |
| Web pages or routes | `pnpm --filter @aec/web test:e2e` |
| Shared UI components | `pnpm --filter @aec/ui test` |
| Alembic migrations | `cd apps/api && alembic upgrade head && alembic downgrade -1 && alembic upgrade head` |
| Terraform | `cd infra/terraform && terraform fmt -recursive && terraform validate` |

The Makefile has shortcuts: `make test`, `make test-api`, `make test-web`,
`make test-api-integration` (the last one spins up Postgres + Redis from
docker-compose first).

## Style and conventions

### Python

- Strict ruff + mypy. The pinned versions are in `apps/api/requirements-dev.txt`
  — local and CI must agree, so don't `pip install ruff` outside the requirements
  file.
- `from __future__ import annotations` at the top of every module.
- FastAPI routes return the `Envelope[T]` shape. The helpers are in
  `apps/api/core/envelope.py`.
- Tenant-scoped queries should go through `db.deps.get_db`, which sets the
  `app.current_org_id` Postgres GUC. Don't bypass to the admin session unless
  you're explicitly testing or seeding cross-tenant state.

### TypeScript

- Strict mode, no `any`. If you genuinely need it, `as never` and a comment
  explaining why.
- TanStack Query for all server state. Optimistic updates use `onMutate` +
  `onError` rollback (see `apps/web/hooks/pulse/useTasks.ts` for the canonical
  pattern).
- Shared types live in `packages/types/`, mirroring Pydantic schemas. Drift
  is a build-time error.

### Commits

Conventional prefix is preferred but not enforced:

```
feat(pulse): add Kanban drag-drop with optimistic update
fix(api): tenant-scoped query missed in change_orders.list
chore(deps): bump pydantic 2.9.2 → 2.13.3
docs(testing): document the integration lane
test(web): playwright spec for proposals/[id]
```

Subject line under 70 chars. Body wraps at 80. The body explains the *why*,
not the *what* (the diff covers what).

## Migrations

Alembic, linear history. To add one:

```bash
cd apps/api
alembic revision -m "add_quota_table_to_codeguard"
# edit the generated file
alembic upgrade head        # apply locally
alembic downgrade -1        # verify roundtrip
alembic upgrade head        # back to head
```

CI verifies `alembic heads` returns exactly one head — branched migrations
must be merged downstream before they land on `main`.

## Tests

Four lanes, each gated separately in CI:

1. **API unit** (`apps/api/tests/`) — uses `FakeAsyncSession`, no real
   Postgres. ~10s. Mock the AI pipelines at the entrypoint
   (`ml.pipelines.<module>.<fn>`); never reach the real LLM in unit tests.

2. **API integration** (`pytest --integration`) — opt-in, requires a real
   Postgres with the `aec_app` role. Tests RLS, real upserts, full
   pipelines. Run via `make test-api-integration`.

3. **UI components** (`packages/ui` Vitest + React Testing Library) — fast
   jsdom suite for prop / state / handler logic in isolation. ~2s.

4. **Web E2E** (`apps/web/tests/e2e/`) — Playwright. The config boots
   `next dev` itself and intercepts API calls via `page.route()`, so no
   backend needed. Run with `make test-web`.

See [`docs/testing.md`](./docs/testing.md) for full details on each lane.

## Dependencies

Dependabot runs weekly. Two policies make this manageable:

- **Patch / minor bumps** → grouped into a single PR per ecosystem; auto-merged
  by `.github/workflows/dependabot-auto-merge.yml` once CI is green.
- **Major bumps for framework deps** → ignored entirely (see
  `.github/dependabot.yml`). Bump manually in the relevant `package.json`
  / `requirements.txt` when you're ready to do the migration.

To add a new dependency:

- npm: edit the package's `package.json`, then `pnpm install` to update the
  lockfile. Don't manually edit `pnpm-lock.yaml`.
- pip: append to `apps/{api,worker}/requirements.txt` with an explicit pin.
  We don't use `requirements.in` / `pip-compile`.

## Security

- Don't commit secrets. `.env` is gitignored; always read from environment.
- The `detect-private-key` pre-commit hook will catch obvious cases.
- For supply-chain concerns, the Security CI job posts `pnpm audit` and
  `pip-audit` JSON as artifacts on every PR. It's non-blocking by design —
  triage the report when something high-severity lands, don't gate every push.

## Asking questions

Open a GitHub Discussion or reach out to the maintainer. PRs welcome, but
if you're proposing something with material architectural impact (a new
module, a schema change crossing several modules, replacing a major dep),
sketch the idea in an issue first so we can talk it through before you write
the code.
