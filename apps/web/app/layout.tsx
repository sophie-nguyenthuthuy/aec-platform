import type { Metadata } from "next";
import { cookies } from "next/headers";
import { getLocale, getMessages } from "next-intl/server";
import type { ReactNode } from "react";

import type { SessionContext } from "@/lib/auth-context";
import { supabaseServer } from "@/lib/supabase-server";
import { PwaInstaller } from "@/components/PwaInstaller";

import { Providers } from "./providers";
import "./globals.css";

export const metadata: Metadata = {
  title: "AEC Platform",
  description: "AI-powered platform for architecture, engineering, and construction",
  applicationName: "AEC Platform",
  // The manifest unlocks install-to-home-screen on Android/iOS + the
  // PWA app-switcher tile. Served from /public/manifest.webmanifest.
  manifest: "/manifest.webmanifest",
  // Apple-specific status-bar styling and home-screen title. The
  // standard manifest fields are ignored by iOS Safari until 17.4+.
  appleWebApp: {
    capable: true,
    title: "AEC",
    statusBarStyle: "default",
  },
  icons: {
    icon: [
      { url: "/icons/icon-192.svg", sizes: "192x192", type: "image/svg+xml" },
      { url: "/icons/icon-512.svg", sizes: "512x512", type: "image/svg+xml" },
    ],
    apple: [{ url: "/icons/icon-192.svg", sizes: "192x192" }],
  },
};

// Theme color drives the Android status bar tint + the Chrome address-bar
// colour in standalone mode. Slate-900 to match the dashboard chrome.
// `viewport` is a separate Next.js export (Metadata API split since 14.0).
export const viewport = {
  themeColor: "#0f172a",
  width: "device-width",
  initialScale: 1,
  // Allow zoom — accessibility. Disabling pinch-to-zoom breaks low-vision
  // users on field-survey pages.
  maximumScale: 5,
};

// Every page mounted under this layout reads request cookies and the Supabase
// session, so static prerender is meaningless — the rendered HTML depends on
// per-request auth. Marking the layout `force-dynamic` makes that explicit
// (otherwise Next's prerender pass walks each page and trips the layout's
// `cookies()` / `supabaseServer()` calls). Keeps `next build` honest and
// avoids the "missing Supabase env" prerender errors on build machines that
// don't have the runtime secrets.
export const dynamic = "force-dynamic";

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
  // project. Defense-in-depth: gate on `NODE_ENV !== "production"` too,
  // so a leaked env var can't silently inject a fake session in prod.
  // Matches the bypass in `apps/web/middleware.ts`.
  if (
    process.env.NODE_ENV !== "production" &&
    process.env.E2E_BYPASS_AUTH === "1"
  ) {
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
        {/* PWA glue: registers /sw.js in prod + parks the install
            prompt for the "Cài app" CTA. No-op on desktop / dev. */}
        <PwaInstaller />
      </body>
    </html>
  );
}
