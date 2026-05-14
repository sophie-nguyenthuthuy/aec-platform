import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

/**
 * Contract tests for the OAuth callback route at /auth/callback.
 *
 * Coverage:
 *  1. Provider error (consent denied, account mismatch) → redirect to
 *     /login with the `error_description` carried through.
 *  2. Missing `code` query param → redirect to /login with
 *     `?error=missing_oauth_code` (defensive — should never happen
 *     in practice, but a hand-crafted callback URL shouldn't crash).
 *  3. Successful code exchange + safe `?next=/dashboard` →
 *     redirect to /dashboard.
 *  4. Open-redirect defense: `?next=//evil.com/x` → coerced back to
 *     `/`. Same for `?next=https://evil.com/x`. This is the
 *     load-bearing test; without it, a phishing link crafted to
 *     redirect a logged-in user offsite would work.
 *  5. exchangeCodeForSession failure → `/login?error=...` with the
 *     supabase error message passed through.
 *
 * We mock `supabaseServer` so the test never touches network. The
 * route is a `GET` route handler, so we invoke it with a
 * `NextRequest` directly.
 */

import { NextRequest } from "next/server";

// Hoist the mock — Next's route handlers import supabaseServer at
// module top level, so the spy needs to be wired before the route
// is imported.
const exchangeCodeForSession = vi.fn();
vi.mock("@/lib/supabase-server", () => ({
  supabaseServer: () =>
    Promise.resolve({
      auth: { exchangeCodeForSession },
    }),
}));


function makeRequest(query: string): NextRequest {
  return new NextRequest(new URL(`http://localhost:3000/auth/callback?${query}`));
}


beforeEach(() => {
  exchangeCodeForSession.mockReset();
});

afterEach(() => {
  vi.clearAllMocks();
});


describe("/auth/callback", () => {
  test("provider error → redirect to /login with description", async () => {
    const { GET } = await import("../route");
    const res = await GET(
      makeRequest("error=access_denied&error_description=The+user+denied+consent"),
    );
    expect(res.status).toBe(307);
    const location = res.headers.get("location") || "";
    expect(location).toContain("/login");
    expect(location).toContain("error=The+user+denied+consent");
    expect(exchangeCodeForSession).not.toHaveBeenCalled();
  });

  test("missing code → /login?error=missing_oauth_code", async () => {
    const { GET } = await import("../route");
    const res = await GET(makeRequest(""));
    expect(res.status).toBe(307);
    expect(res.headers.get("location") || "").toContain("error=missing_oauth_code");
  });

  test("successful exchange + safe next → redirect to next", async () => {
    exchangeCodeForSession.mockResolvedValue({ error: null });
    const { GET } = await import("../route");
    const res = await GET(makeRequest("code=abc123&next=/projects"));
    expect(res.status).toBe(307);
    expect(res.headers.get("location") || "").toContain("/projects");
    expect(exchangeCodeForSession).toHaveBeenCalledWith("abc123");
  });

  test("open-redirect: protocol-relative next is rejected", async () => {
    exchangeCodeForSession.mockResolvedValue({ error: null });
    const { GET } = await import("../route");
    const res = await GET(makeRequest("code=abc&next=//evil.com/phish"));
    expect(res.status).toBe(307);
    const location = res.headers.get("location") || "";
    expect(location).not.toContain("evil.com");
    // Should land on root (path only, ignoring host)
    expect(new URL(location).pathname).toBe("/");
  });

  test("open-redirect: absolute https next is rejected", async () => {
    exchangeCodeForSession.mockResolvedValue({ error: null });
    const { GET } = await import("../route");
    const res = await GET(makeRequest("code=abc&next=https://evil.com/x"));
    expect(res.status).toBe(307);
    const location = res.headers.get("location") || "";
    expect(location).not.toContain("evil.com");
    expect(new URL(location).pathname).toBe("/");
  });

  test("supabase exchange failure → /login?error=<message>", async () => {
    exchangeCodeForSession.mockResolvedValue({
      error: { message: "Code already used" },
    });
    const { GET } = await import("../route");
    const res = await GET(makeRequest("code=replayed"));
    expect(res.status).toBe(307);
    const location = res.headers.get("location") || "";
    expect(location).toContain("/login");
    expect(location).toContain("error=Code+already+used");
  });
});
