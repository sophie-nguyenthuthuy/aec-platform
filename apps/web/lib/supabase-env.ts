/**
 * Supabase env-var validation. Imported by every Supabase client factory so a
 * misconfigured deploy fails at module-load with a clear message instead of
 * a runtime "fetch undefined" deep inside @supabase/supabase-js.
 *
 * Both vars are inlined into the browser bundle by Next.js (NEXT_PUBLIC_*),
 * so they're safe to ship publicly — the publishable key is the new
 * equivalent of the old `anon` key.
 */
export interface SupabaseEnv {
  url: string;
  publishableKey: string;
}

export function readSupabaseEnv(): SupabaseEnv {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const publishableKey = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;
  if (!url || !publishableKey) {
    throw new Error(
      "Missing Supabase env: NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY are required.",
    );
  }
  return { url, publishableKey };
}
