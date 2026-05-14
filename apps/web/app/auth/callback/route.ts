import { NextResponse, type NextRequest } from "next/server";

import { supabaseServer } from "@/lib/supabase-server";

/**
 * OAuth + magic-link callback handler.
 *
 * Supabase's PKCE flow drops the user back here with `?code=...` after
 * the provider (Google Workspace / Microsoft Entra / etc.) hands off
 * the auth response. We exchange the code for a session cookie via
 * `exchangeCodeForSession`, then redirect to `?next=` (or `/` if
 * unset). The session cookie set during the exchange flows back through
 * the response, which is why we must build the redirect with
 * `NextResponse.redirect` AFTER the supabase call — otherwise the
 * cookie write loses the response context.
 *
 * If the exchange fails (expired code, replayed link, browser cleared
 * cookies mid-flight) we route back to /login with an `error=` query
 * param so the login page can surface a recoverable message instead
 * of a blank loop.
 */
export async function GET(request: NextRequest) {
  const url = new URL(request.url);
  const code = url.searchParams.get("code");
  const errorParam = url.searchParams.get("error");
  const errorDescription = url.searchParams.get("error_description");
  const next = url.searchParams.get("next") || "/";

  // The provider may surface its own error (consent denied, account
  // mismatch). Pass it through untouched — Supabase's error_description
  // is already user-friendly.
  if (errorParam) {
    const back = new URL("/login", request.url);
    back.searchParams.set("error", errorDescription || errorParam);
    return NextResponse.redirect(back);
  }

  if (!code) {
    const back = new URL("/login", request.url);
    back.searchParams.set("error", "missing_oauth_code");
    return NextResponse.redirect(back);
  }

  const supabase = await supabaseServer();
  const { error } = await supabase.auth.exchangeCodeForSession(code);

  if (error) {
    const back = new URL("/login", request.url);
    back.searchParams.set("error", error.message);
    return NextResponse.redirect(back);
  }

  // Defense against open-redirect: only allow same-origin `next` paths.
  // Absolute URLs and protocol-relative paths are rejected and we fall
  // back to root.
  const safeNext = isSafeNext(next) ? next : "/";
  return NextResponse.redirect(new URL(safeNext, request.url));
}


/**
 * A redirect target is safe iff it's a same-origin path beginning with
 * a single `/` (no protocol, no host). Rejects `//evil.com/...` and
 * `https://evil.com/x` injection attempts.
 */
function isSafeNext(next: string): boolean {
  if (!next.startsWith("/")) return false;
  if (next.startsWith("//")) return false;
  return true;
}
