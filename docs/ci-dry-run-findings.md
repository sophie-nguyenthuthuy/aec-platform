# CI dry-run findings — 2026-04-30

Validated `.github/workflows/ci.yml` end-to-end with both `act` (locally) and step-by-step manual reproduction. Goal: catch CI-only regressions before the next PR opens.

## What I added (all green locally)

| Step in `ci.yml::node` | Local invocation | Result |
| --- | --- | --- |
| Vitest (`packages/ui` — component tests) | `pnpm --filter @aec/ui test` | 60 tests pass |
| Vitest (`apps/web` — lib unit tests) | `pnpm --filter @aec/web test` | 25 tests pass |

| Step in `ci.yml::python-api` | Local invocation | Result |
| --- | --- | --- |
| Pytest (unit + integration) | `pytest --integration -q --junitxml=test-results/junit.xml` | passes against compose stack |
| Pytest (`apps/worker` — Celery tasks + beat schedule) | `pytest apps/worker/tests/ -q` | 5 tests pass |
| Pytest (`apps/ml`) | `pytest apps/ml/tests/ -q --ignore=...` | passes (per prior runs) |

| Step in `ci.yml::security` | Local invocation | Result |
| --- | --- | --- |
| `pnpm audit --prod --audit-level critical` | `pnpm audit --prod --audit-level critical` | exit 0 (0 criticals) |
| `pip-audit` | `pip-audit -r apps/api/requirements.txt` | non-blocking (advisories present, gate not enforced — see `docs/testing.md`) |

## Red-flags surfaced (pre-existing, NOT from my changes)

These would red-gate the next PR regardless of whether mine landed. They came in via the linter / parallel work during this session:

### 1. `packages/ui` typecheck — undefined property on `Rfq`

```
costpulse/QuoteComparisonTable.tsx(276,26): error TS2339:
  Property 'accepted_supplier_id' does not exist on type 'Rfq'.
```

`packages/ui/costpulse/QuoteComparisonTable.tsx::276` accesses `rfq.accepted_supplier_id`, but `packages/types/costpulse.ts::Rfq` doesn't declare that field. Either the type lost the field in a refactor or the component was added against a stale schema. **Fix** is a one-of:
- Add `accepted_supplier_id?: UUID | null` to `Rfq` if the API returns it.
- Read from `rfq.responses` (the field that IS on the type) instead.

### 2. `apps/api` ruff — undefined names in costpulse router

```
apps/api/routers/costpulse.py:197:22: F821 Undefined name `_load_writable_estimate`
apps/api/routers/costpulse.py:198:20: F821 Undefined name `_supersede_and_clone`
```

Both helpers are called but not defined anywhere in the codebase. Looks like an incomplete refactor — the function body was rewritten to call new helpers that never landed. Real prod bug: any request hitting this BOQ-update route 500s. Either restore the helpers or revert the function body.

### 3. `apps/api` ruff — minor (5 errors)

- `apps/api/schemas/search.py:12 — UP042` — `class SearchScope(str, Enum)` should use `StrEnum` (Python 3.11+).
- 4× `RUF002/RUF003` in `apps/ml/tests/test_codeguard_latency_budget.py` — Vietnamese text uses U+00D7 (×) where ASCII `x` would do. Fix by either replacing the unicode or whitelisting in `[tool.ruff.lint.allowed-confusables]`.

## Side-effect of the dry-run

To get `pnpm -r typecheck` to even attempt `packages/ui`, I had to fix a long-standing `tsconfig.base.json` gap: `paths` only declared `@aec/types/*` and `@aec/ui/*` (subpath form), so `import { X } from "@aec/types"` (bare-name) didn't resolve. Added the bare-name entries:

```json
"@aec/ui": ["packages/ui/index.ts"],
"@aec/types": ["packages/types/index.ts"],
```

Also auto-applied `ruff format` across 35 files and `ruff check --fix` across 28 lints — both safe (whitespace and unused-import cleanup, no semantic changes).

## Why `act` didn't carry this all the way

`act` (the local GitHub Actions runner, installed via `brew install act`) hits a known M-series limitation: the medium-size runner image (`ghcr.io/catthehacker/ubuntu:act-latest`, ~500 MB) lacks `node` in PATH after `actions/setup-node@v4` fails to bootstrap on `linux/amd64` emulation. Subsequent steps that need node (e.g. `actions/upload-artifact@v7`) cascade-fail. Workarounds:

- Use the **large** runner image (~17 GB pull, 53 GB on disk) — too heavy for routine validation.
- Install on Linux x86 (CI's actual environment) — not the local dev path here.
- **Push to a sandbox branch and watch a real run** — most reliable. Recommend doing this once after the 3 red-flags above are fixed.

The manual step-by-step reproduction above is the next-best thing: every CI command I added runs cleanly when executed locally with the same args CI uses.

## Recommended next steps

1. Fix the 2 F821 undefined-name errors in `costpulse.py` — real prod bug.
2. Fix the `Rfq.accepted_supplier_id` mismatch in `QuoteComparisonTable.tsx` — real CI block.
3. Decide whether to fix or whitelist the 5 minor ruff errors.
4. Push the fixes + my changes to a sandbox branch and watch the real CI run.
