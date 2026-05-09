/**
 * Supabase env-var validation. Imported by every Supabase client factory so a
 * misconfigured deploy fails with a clear message instead of a runtime
 * "fetch undefined" deep inside @supabase/supabase-js.
 *
 * Both vars are inlined into the browser bundle by Next.js (NEXT_PUBLIC_*),
 * so they're safe to ship publicly — the publishable key is the new
 * equivalent of the old `anon` key.
 *
 * Lazy on purpose: callers invoke `readSupabaseEnv()` from inside client
 * factories (`supabaseServer`, `supabaseBrowser`, middleware), never at
 * module top-level. That means the throw fires the first time a *request*
 * actually needs Supabase — not at import time. The Next.js production
 * build phase still walks server-component module graphs and may invoke
 * factory functions during prerender; for that one phase we return
 * placeholder values so the build completes. Real requests at runtime
 * (`NEXT_PHASE` is undefined or `phase-production-server`) still throw
 * loudly when the env is missing.
 */
export interface SupabaseEnv {
  url: string;
  publishableKey: string;
}

// Sentinel placeholders used only during `next build` prerender when the
// real env is absent. Chosen to be obviously non-functional if they ever
// leak into a runtime fetch — `https://build-time-placeholder.invalid`
// is in the reserved `.invalid` TLD (RFC 6761) so DNS will refuse it.
const BUILD_PLACEHOLDER_URL = "https://build-time-placeholder.invalid";
const BUILD_PLACEHOLDER_KEY = "build-time-placeholder-key";

export function readSupabaseEnv(): SupabaseEnv {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const publishableKey = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;
  if (!url || !publishableKey) {
    if (process.env.NEXT_PHASE === "phase-production-build") {
      // Allow `next build` to complete on machines without a real Supabase
      // config (e.g. CI build gates that don't have the secrets). Any
      // server component that tries to actually *call* Supabase during
      // prerender will fail at the network layer, not here — and the root
      // layout opts out of prerender via `export const dynamic = "force-dynamic"`,
      // so this path should not execute at runtime.
      return { url: BUILD_PLACEHOLDER_URL, publishableKey: BUILD_PLACEHOLDER_KEY };
    }
    throw new Error(
      "Missing Supabase env: NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY are required.",
    );
  }
  return { url, publishableKey };
}
