import { expect, test } from "@playwright/test";

/**
 * End-to-end auth smoke. Hits a *real* Supabase project + the local API.
 *
 * What this catches that the mocked e2e suite can't:
 *   * `@supabase/ssr` cookie format changes (it's broken twice in 2024 alone)
 *   * Middleware redirect logic against the actual cookie shape
 *   * The api `/me/orgs` ↔ web layout SSR contract — orgs returned by
 *     the api have to match the `SessionContext.orgs` type the layout reads
 *   * Sign-out actually clearing the cookie and bouncing to /login
 */

const EMAIL = process.env.AEC_REAL_AUTH_EMAIL ?? "dev@aec-platform.vn";
const PASSWORD = process.env.AEC_REAL_AUTH_PASSWORD ?? "DevPassw0rd!";

test.describe("real Supabase auth", () => {
  test("unauthenticated visit redirects to /login with `next` preserved", async ({ page }) => {
    const res = await page.goto("/winwork");
    // Final URL after redirect chain.
    expect(page.url()).toContain("/login");
    expect(page.url()).toContain("next=");
    // 200 because /login renders fine; the redirect happens at middleware.
    expect(res?.status()).toBe(200);
    // The login form is the visible UI cue.
    await expect(page.getByRole("button", { name: /Đăng nhập/i })).toBeVisible();
  });

  test("sign in → dashboard renders with org switcher → sign out clears session", async ({
    page,
  }) => {
    // Land on /login (middleware will bounce us here from /).
    await page.goto("/");
    await expect(page).toHaveURL(/\/login/);

    // Submit credentials. The form's action calls supabase.auth.signInWithPassword
    // and then router.replace(next).
    await page.getByLabel(/Email/i).fill(EMAIL);
    await page.getByLabel(/Mật khẩu/i).fill(PASSWORD);
    await page.getByRole("button", { name: /Đăng nhập/i }).click();

    // After successful sign-in we get redirected back to `/` (the default
    // `next` value), which itself redirects server-side to `/winwork`
    // (the default landing page — see `app/page.tsx`'s
    // `redirect("/winwork")`). Either landing point is fine; what
    // matters is we left `/login` with a valid session.
    await expect(page).toHaveURL(/^http:\/\/127\.0\.0\.1:3102\/(?:winwork|\?|$)/);
    await expect(page.getByText("Dev Org")).toBeVisible();
    await expect(page.getByText(EMAIL)).toBeVisible();

    // Org switcher renders the role badge for single-org users in a
    // dropdown — for single-org it might be hidden, just check the
    // section header.
    await expect(page.getByText(/Tổ chức/i)).toBeVisible();

    // Sign-out: server action that clears the cookie + redirects to /login.
    await page.getByRole("button", { name: /Đăng xuất/i }).click();
    await expect(page).toHaveURL(/\/login/);

    // Cookie is gone — visiting a protected route must redirect again.
    await page.goto("/winwork");
    await expect(page).toHaveURL(/\/login/);
  });

  test("invalid credentials surface the supabase error message", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel(/Email/i).fill(EMAIL);
    await page.getByLabel(/Mật khẩu/i).fill("definitely-not-the-password");
    await page.getByRole("button", { name: /Đăng nhập/i }).click();

    // Supabase returns "Invalid login credentials" — the form renders it
    // verbatim into the error chip.
    await expect(page.getByText(/Invalid login credentials/i)).toBeVisible({
      timeout: 10_000,
    });
    // We're still on /login; no cookie was set.
    expect(page.url()).toContain("/login");
  });
});
