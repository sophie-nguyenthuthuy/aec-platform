"use server";

import { cookies } from "next/headers";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { supabaseServer } from "@/lib/supabase-server";

const ACTIVE_ORG_COOKIE = "aec-active-org";

/**
 * Server action: pin the active org. The dashboard layout reads this cookie
 * on every request to decide which `X-Org-ID` to send to the api. We
 * `revalidatePath("/")` so the layout re-runs against the new cookie and
 * every cached server component picks up the new org's data.
 */
export async function switchOrg(orgId: string): Promise<void> {
  // Sanity check the input — orgs are UUIDs.
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(orgId)) {
    throw new Error("Invalid org id");
  }
  const store = await cookies();
  store.set(ACTIVE_ORG_COOKIE, orgId, {
    path: "/",
    httpOnly: true,
    sameSite: "lax",
    // 30 days. The cookie just remembers a UI choice; refresh on every
    // login is fine.
    maxAge: 60 * 60 * 24 * 30,
  });
  revalidatePath("/", "layout");
}

/** Server action: clear the Supabase session and bounce the user to /login. */
export async function signOut(): Promise<void> {
  const supabase = await supabaseServer();
  await supabase.auth.signOut();
  redirect("/login");
}
