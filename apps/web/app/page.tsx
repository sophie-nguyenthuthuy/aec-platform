import { redirect } from "next/navigation";

import { supabaseServer } from "@/lib/supabase-server";

import LandingPage from "./_marketing/LandingPage";

/**
 * Root `/` route. Two branches:
 *
 *   - Authed user (Supabase session cookie present + valid) → bounce
 *     to /inbox so the dashboard chrome takes over.
 *   - Anonymous visitor → render the public marketing landing page.
 *
 * This route is in PUBLIC_ROUTES (middleware.ts), so anonymous traffic
 * doesn't get punted to /login.
 *
 * The marketing JSX lives in `_marketing/LandingPage` so it can stay
 * a client component (CTAs, scroll behaviour) while this entry stays
 * an async server component for the auth check.
 */
export default async function RootPage() {
  const supabase = await supabaseServer();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (user) {
    redirect("/inbox");
  }

  return <LandingPage />;
}

// Force dynamic so the auth check runs per-request (don't statically
// cache the marketing page with a stale auth verdict).
export const dynamic = "force-dynamic";
