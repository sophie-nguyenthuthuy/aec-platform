import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";
import type { SupabaseClient } from "@supabase/supabase-js";

import { readSupabaseEnv } from "./supabase-env";

/** Server-side Supabase client for Server Components / Server Actions / Route
 *  Handlers. Reads the request cookies via `next/headers` — must be called
 *  inside a request scope. The `setAll` callback may be a no-op when invoked
 *  from a Server Component (where cookies are read-only); the middleware
 *  handles the actual cookie refresh. */
export async function supabaseServer(): Promise<SupabaseClient> {
  const { url, publishableKey } = readSupabaseEnv();
  const cookieStore = await cookies();

  return createServerClient(url, publishableKey, {
    cookies: {
      getAll() {
        return cookieStore.getAll();
      },
      setAll(cookiesToSet) {
        try {
          for (const { name, value, options } of cookiesToSet) {
            cookieStore.set(name, value, options);
          }
        } catch {
          // Server Components can't mutate cookies. Middleware refreshes
          // the session before the page renders, so this is fine.
        }
      },
    },
  });
}
