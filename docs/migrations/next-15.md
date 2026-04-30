# Migrating to Next.js 15

## Why this is queued

Two HIGH-severity advisories against `next@14.2.x` ship without a backport to the 14.2 line:

| GHSA | What | Patched in |
| --- | --- | --- |
| `next` HTTP request deserialization → DoS | crafted requests can saturate the dev/prod server's parser | **15.0.8** |
| `next` Server Components → DoS | crafted server-component flow can OOM the worker | **15.5.15** |

Both surface in `pnpm audit --prod`. The current security CI gate (`.github/workflows/ci.yml::security`) is at `--audit-level critical` because gating on HIGH today would red every PR until this migration lands. **After this migration ships and `pnpm audit --prod --audit-level high` returns 0**, ratchet the gate to `high`.

The `glob`-CLI HIGH advisory does NOT clear with this migration — it's a CLI vector that doesn't apply to library use, and the patch is in `glob@10.5.0` which neither Next 14 nor Next 15 brings in. Treat as a pin or allowlist; don't gate on it.

## Pre-migration state (2026-04)

```
apps/web/package.json
  next:               14.2.35
  next-intl:          ^3.20.0   (resolved 3.26.5)
  eslint-config-next: 14.2.35
packages/ui/package.json
  next (devDeps):     14.2.35
packages/config/package.json
  eslint-config-next: 14.2.35
```

The codebase already pre-applies the **biggest** Next 15 breaking change: `await cookies()` and `await headers()` in Server Components / Server Actions / Route Handlers. Verified call sites:

```
apps/web/app/layout.tsx:101                   await cookies()
apps/web/app/(dashboard)/_actions/session.ts  await cookies()
apps/web/lib/supabase-server.ts:14            await cookies()
```

This is a no-op on Next 14 (the API is sync but `await` on a sync value is fine) and the correct shape on Next 15. So the migration is mostly **dependency alignment + smoke-test**, not a code rewrite.

## What 15.x actually breaks for us

| Area | 14.2 | 15.x | Our exposure |
| --- | --- | --- | --- |
| `cookies()` / `headers()` / `draftMode()` | sync | **async** | ✅ already `await`-ed |
| `params` / `searchParams` in pages | sync | **async** | ⚠️ check all `[id]/page.tsx` route handlers |
| Caching defaults (`fetch`, `GET` route handlers) | cached by default | **uncached by default** | ⚠️ audit any `fetch` we want cached |
| `next/image` quality config | wide range | quality must be allow-listed | low — we only use defaults |
| `experimental.runtime` etc. | various | renamed/moved | none — we don't set these |
| ESLint `next/core-web-vitals` rules | 14.2 set | tightened in 15 | low — Lint may flag new rules |
| React 19 peer | optional | **default** | ⚠️ check `@types/react` aligns |

**The two real risk areas are `params`/`searchParams` and caching defaults.** Everything else is bookkeeping.

## Step-by-step

Land each step as its own commit so a regression bisects cleanly.

### 1. Bump deps

```bash
# In apps/web/package.json:
#   "next":               "14.2.35"  → "15.5.15"
#   "next-intl":          "^3.20.0"  → "^4.9.2"
#   "eslint-config-next": "14.2.35"  → "15.5.15"
#
# In packages/ui/package.json devDeps:
#   "next":               "14.2.35"  → "15.5.15"
#
# In packages/config/package.json:
#   "eslint-config-next": "14.2.35"  → "15.5.15"

pnpm install
```

`@supabase/ssr` has no Next peer — works with both. No bump needed there.

### 2. Audit `params` / `searchParams` usage

These were sync in 14.2, async in 15. Find every call site and `await` it:

```bash
# Server-component pages where params is destructured from props
grep -rn "params:.*}" apps/web/app --include="*.tsx" --include="*.ts" \
  | grep -E "\\[.*\\]/page\\.tsx"

# searchParams in any page or layout
grep -rn "searchParams" apps/web/app --include="*.tsx" --include="*.ts"
```

For each match:

```diff
- export default function Page({ params }: { params: { id: string } }) {
-   const { id } = params;
+ export default async function Page({ params }: { params: Promise<{ id: string }> }) {
+   const { id } = await params;
```

Same shape for `searchParams`. Client components calling `useParams()` / `useSearchParams()` are unaffected.

### 3. Audit `fetch` caching

In 14.2, `fetch()` in Server Components and `GET` route handlers was cached unless opted out. In 15.x, it's uncached unless opted **in**. We have one direct-fetch site:

```
apps/web/app/layout.tsx::fetchOrgs  →  fetch(`${apiUrl}/api/v1/me/orgs`, { cache: "no-store" })
```

Already opts out — no behavior change. Anything else hitting `fetch` from server code should be reviewed; if cached behavior was being relied on, add `{ cache: "force-cache", next: { revalidate: 60 } }` explicitly.

### 4. Run the test gauntlet

```bash
make test                              # api unit + web E2E (no infra)
make test-api-integration              # full lane against compose stack
pnpm --filter @aec/web build           # ensures prod-build TS strict checks pass
pnpm --filter @aec/web typecheck       # explicit typecheck pass
```

**Particular attention to:**

- `apps/web/tests/e2e/projects.spec.ts:146` — exercises a `[id]/page.tsx` detail page with module roll-ups. If `params` becomes async, this will surface first.
- `apps/web/tests/e2e/drawbridge-document-detail.spec.ts` — same shape, hits the PDF viewer route.
- The Supabase auth bypass (`E2E_BYPASS_AUTH=1` in middleware + layout) — middleware.ts API surface didn't change in 15, but verify the `NextResponse.next({ request })` form still works.

### 5. Re-run audits

```bash
pnpm audit --prod --audit-level high
# Expected: zero high advisories (clears both DoS issues from the table above).
```

### 6. Tighten the gate

After the migration PR merges and the `pnpm audit --prod --audit-level high` step is reliably green, edit `.github/workflows/ci.yml::security`:

```diff
- pnpm audit --prod --audit-level critical
+ pnpm audit --prod --audit-level high
```

That moves the gate from "block CRITICAL" to "block HIGH", catching the next regression in the CRIT/HIGH band rather than the CRIT band only.

## Rollback

If the migration ships and surfaces a runtime bug we can't fix quickly:

```bash
git revert <migration-commit>
pnpm install
```

The `next-intl` 4.x → 3.x revert is the trickiest piece — 4.x changed how `getRequestConfig` is structured. Keeping both bumps in a single revert-friendly commit makes this safer.

## Out of scope

- **App Router → Pages Router** migration. Not needed; we stay on App.
- **React 19** as a forced peer. Next 15 supports both 18 and 19; we keep 18.3.1 unless there's a specific reason (Recharts and `next-intl` 4 both still test against 18).
- **Turbopack as default**. Stick with webpack until Turbopack stabilizes for production builds — we don't yet need the dev-mode speed boost enough to take on the build-time risk.
- The `glob`-CLI HIGH advisory. Treat as informational — not exploitable in our usage pattern.
