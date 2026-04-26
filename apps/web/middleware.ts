import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

import { readSupabaseEnv } from "./lib/supabase-env";

/**
 * Per-request Supabase auth pass:
 *   1. Build a server client wired to this request's cookies.
 *   2. Call `getUser()` — Supabase rotates the access token here when the
 *      old one is close to expiring; the new cookie ends up on the response.
 *   3. Redirect unauthenticated requests for protected routes to /login,
 *      preserving the intended destination via `?next=`.
 *
 * Public routes (`/login`, the RFQ supplier portal, static assets) skip
 * the redirect but still go through the cookie-refresh path so the auth
 * client stays in sync if the user is actually signed in.
 */

const PUBLIC_ROUTES = [
  "/login",
  "/auth", // /auth/callback for magic links / OAuth
  "/rfq", // supplier-portal token-auth pages
  "/api/health",
];

function isPublicRoute(pathname: string): boolean {
  return PUBLIC_ROUTES.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}

export async function middleware(request: NextRequest) {
  // Test escape hatch — Playwright's webServer block sets this so E2E specs
  // (which mock all `/api/v1/...` traffic via `page.route` and never talk to
  // a real Supabase) don't have to provision real Supabase env or stub
  // server-side auth handshakes. Production never sets this; the variable
  // name is intentionally explicit so a stray export couldn't silently
  // disable auth.
  if (process.env.E2E_BYPASS_AUTH === "1") {
    return NextResponse.next({ request });
  }

  const { url, publishableKey } = readSupabaseEnv();

  // Start with a passthrough response. Supabase mutates its cookies via
  // `setAll`; we copy those onto the response we eventually return.
  let response = NextResponse.next({ request });

  const supabase = createServerClient(url, publishableKey, {
    cookies: {
      getAll() {
        return request.cookies.getAll();
      },
      setAll(cookiesToSet) {
        for (const { name, value } of cookiesToSet) {
          request.cookies.set(name, value);
        }
        response = NextResponse.next({ request });
        for (const { name, value, options } of cookiesToSet) {
          response.cookies.set(name, value, options);
        }
      },
    },
  });

  // Refresh / validate the session.
  const {
    data: { user },
  } = await supabase.auth.getUser();

  const { pathname, search } = request.nextUrl;

  if (!user && !isPublicRoute(pathname)) {
    const loginUrl = request.nextUrl.clone();
    loginUrl.pathname = "/login";
    loginUrl.search = `?next=${encodeURIComponent(pathname + search)}`;
    return NextResponse.redirect(loginUrl);
  }

  // Already signed in but landing on /login? Send them home.
  if (user && pathname === "/login") {
    const home = request.nextUrl.clone();
    home.pathname = "/";
    home.search = "";
    return NextResponse.redirect(home);
  }

  return response;
}

export const config = {
  // Skip Next internals + static files; the middleware does cookie work
  // that doesn't matter for those.
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)"],
};
