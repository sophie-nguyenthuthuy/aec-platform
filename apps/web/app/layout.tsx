import type { Metadata } from "next";
import { cookies } from "next/headers";
import { getLocale, getMessages } from "next-intl/server";
import type { ReactNode } from "react";

import type { SessionContext } from "@/lib/auth-context";
import { supabaseServer } from "@/lib/supabase-server";

import { Providers } from "./providers";
import "./globals.css";

export const metadata: Metadata = {
  title: "AEC Platform",
  description: "AI-powered platform for architecture, engineering, and construction",
};

const ACTIVE_ORG_COOKIE = "aec-active-org";

interface OrgRow {
  id: string;
  name: string;
  role: string;
}

/** Fetch the user's org memberships from the api. Auto-provisions a `users`
 *  row server-side on first login. Returns an empty list if the api is down
 *  or the user has no memberships yet (UI shows an empty state). */
async function fetchOrgs(token: string): Promise<OrgRow[]> {
  const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  try {
    const res = await fetch(`${apiUrl}/api/v1/me/orgs`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
    });
    if (!res.ok) return [];
    const env = (await res.json()) as { data: OrgRow[] | null };
    return env.data ?? [];
  } catch {
    return [];
  }
}

export default async function RootLayout({ children }: { children: ReactNode }) {
  const locale = await getLocale();
  const messages = await getMessages();

  let session: SessionContext | null = null;

  // E2E escape hatch — Playwright's webServer block sets this. Skip the
  // Supabase round-trip and inject a deterministic fake session so specs
  // can exercise authenticated pages without provisioning a real Supabase
  // project. Production never sets this; matches the bypass in
  // `apps/web/middleware.ts`.
  if (process.env.E2E_BYPASS_AUTH === "1") {
    session = {
      token: "e2e-fake-token",
      orgId: "00000000-0000-0000-0000-000000000000",
      userId: "00000000-0000-0000-0000-000000000000",
      email: "e2e@test.local",
      locale: locale as "vi" | "en",
      orgs: [
        {
          id: "00000000-0000-0000-0000-000000000000",
          name: "E2E Test Org",
          role: "admin",
        },
      ],
    };
  } else {
    // Pull the Supabase session if any. Middleware redirects unauthenticated
    // requests for protected routes to /login *before* this layout runs, so
    // when we reach here without a user it's a public route (login, RFQ
    // supplier portal) and we render `session=null`.
    const supabase = await supabaseServer();
    const {
      data: { user },
    } = await supabase.auth.getUser();
    const {
      data: { session: supaSession },
    } = await supabase.auth.getSession();

    if (user && supaSession) {
      const orgs = await fetchOrgs(supaSession.access_token);

      // Persist the active org choice in a cookie so the org switcher (tier 2)
      // can update it. Default = the first org returned, alphabetical.
      const cookieStore = await cookies();
      const cookieOrgId = cookieStore.get(ACTIVE_ORG_COOKIE)?.value;
      const activeOrg =
        orgs.find((o) => o.id === cookieOrgId) ?? orgs[0] ?? null;

      if (activeOrg) {
        session = {
          token: supaSession.access_token,
          orgId: activeOrg.id,
          userId: user.id,
          email: user.email ?? "",
          locale: locale as "vi" | "en",
          orgs,
        };
      }
    }
  }

  return (
    <html lang={locale}>
      <body>
        <Providers session={session} locale={locale} messages={messages}>
          {children}
        </Providers>
      </body>
    </html>
  );
}
