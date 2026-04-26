"use client";

import { createBrowserClient } from "@supabase/ssr";
import type { SupabaseClient } from "@supabase/supabase-js";

import { readSupabaseEnv } from "./supabase-env";

let cached: SupabaseClient | null = null;

/** Browser-side Supabase client. Singleton — `@supabase/ssr` reads/writes
 *  the auth cookie set by the server-side client during sign-in. */
export function supabaseBrowser(): SupabaseClient {
  if (cached) return cached;
  const { url, publishableKey } = readSupabaseEnv();
  cached = createBrowserClient(url, publishableKey);
  return cached;
}
