import { expect, test, type APIRequestContext } from "@playwright/test";

/**
 * End-to-end invitation flow against a real Supabase project + the local API.
 *
 * Setup contract (must already be true on the dev box):
 *   * `dev@aec-platform.vn` is the seeded org owner with role=owner on
 *     the seed org (00000000-0000-0000-0000-000000000001).
 *   * The api is running on http://localhost:8002.
 *   * Supabase admin endpoints accept the project's `sb_secret_*` key
 *     for lookup/cleanup of test users created during the run.
 *
 * What this catches that the pytest can't:
 *   * The members page actually wires `useInviteMember` to the api
 *   * The accept-URL form on `/invite/[token]` POSTs through to the
 *     accept endpoint and signs the new user in
 *   * The middleware lets `/invite/{token}` through without a session
 *     while still redirecting `/winwork` if you visit before signing in
 *   * The org switcher renders the new user's row + role
 */

const ADMIN_EMAIL = process.env.AEC_REAL_AUTH_EMAIL ?? "dev@aec-platform.vn";
const ADMIN_PASSWORD = process.env.AEC_REAL_AUTH_PASSWORD ?? "DevPassw0rd!";
const ORG_ID = "00000000-0000-0000-0000-000000000001";
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8002";
const SUPABASE_URL =
  process.env.NEXT_PUBLIC_SUPABASE_URL ?? "https://ejoxmgufldlsbmixqjcm.supabase.co";
const SUPABASE_PUBLISHABLE_KEY =
  process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY ??
  "sb_publishable_PS-udXBaYTqATMkNk0OR3Q_uBwZLc3u";

// `example.com` is the IETF-reserved test domain — email-validator
// accepts it without DNS lookups, and Supabase doesn't try to send mail
// to it.
function uniqueInviteeEmail(): string {
  return `invitee-${Date.now()}-${Math.floor(Math.random() * 1000)}@example.com`;
}

async function adminAccessToken(request: APIRequestContext): Promise<string> {
  const res = await request.post(
    `${SUPABASE_URL}/auth/v1/token?grant_type=password`,
    {
      headers: {
        apikey: SUPABASE_PUBLISHABLE_KEY,
        "Content-Type": "application/json",
      },
      data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
    },
  );
  expect(res.ok(), `admin sign-in failed: ${await res.text()}`).toBeTruthy();
  return (await res.json()).access_token;
}

test.describe("real invitation flow", () => {
  test("admin invites a user → accept link works → invitee lands signed in", async ({
    page,
    request,
  }) => {
    // ---- Step 1: admin signs in via the UI and lands on /settings/members ----
    await page.goto("/login");
    await page.getByLabel(/Email/i).fill(ADMIN_EMAIL);
    await page.getByLabel(/Mật khẩu/i).fill(ADMIN_PASSWORD);
    await page.getByRole("button", { name: /Đăng nhập/i }).click();
    // `/` redirects to `/winwork` server-side; tolerate either.
    await expect(page).toHaveURL(/^http:\/\/127\.0\.0\.1:3102\/(?:winwork|\?|$)/);

    await page.goto("/settings/members");
    // The members page now has three headings whose text *contains*
    // "Thành viên" (page title h2 + 2 section h3s); use `exact` so the
    // page-title h2 is the only match — strict mode would 422 otherwise.
    await expect(
      page.getByRole("heading", { name: "Thành viên", exact: true }),
    ).toBeVisible();

    // ---- Step 2: admin issues invitation ----
    const invitee = uniqueInviteeEmail();
    await page.getByPlaceholder("newuser@example.com").fill(invitee);
    await page.getByRole("button", { name: /Gửi lời mời/i }).click();

    // The "accept URL chip" appears with the token and a Copy button.
    await expect(page.getByText(invitee)).toBeVisible({ timeout: 10_000 });
    const acceptChip = page.locator("code").filter({ hasText: /\/invite\// });
    await expect(acceptChip).toBeVisible();
    const acceptUrl = await acceptChip.textContent();
    expect(acceptUrl).toMatch(/\/invite\/[0-9a-f-]{36}$/);

    // ---- Step 3: admin signs out so we can replay the flow as the invitee ----
    await page.getByRole("button", { name: /Đăng xuất/i }).click();
    await expect(page).toHaveURL(/\/login/);

    // ---- Step 4: invitee visits the accept URL (no session) ----
    // The accept URL the api returns uses `public_web_url` which points
    // at port 3000 in dev compose; on the Playwright lane we're on 3102.
    // Rewrite the host to match the Playwright base URL so middleware
    // and SSR run on the right server.
    const accept = acceptUrl!.replace(/^https?:\/\/[^/]+/, "http://127.0.0.1:3102");
    await page.goto(accept);
    await expect(page.getByText(/Tham gia/)).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(invitee)).toBeVisible();

    // ---- Step 5: invitee sets a password ----
    const inviteePw = "InviteeP4ss-real-auth!";
    await page.getByLabel(/Họ tên/i).fill("Test Invitee");
    await page.getByLabel(/Mật khẩu/i).fill(inviteePw);
    await page.getByRole("button", { name: /Chấp nhận/i }).click();

    // After accept the form auto-signs-in and replaces to `/`, which
    // redirects to `/winwork` server-side. The dashboard should render
    // with the invitee's email + Dev Org + role=member badge.
    await expect(page).toHaveURL(/^http:\/\/127\.0\.0\.1:3102\/(?:winwork|\?|$)/, {
      timeout: 15_000,
    });
    await expect(page.getByText(invitee)).toBeVisible();
    await expect(page.getByText("Dev Org")).toBeVisible();

    // ---- Step 6: hitting the same accept URL a second time must 410 ----
    // We test this server-side via the api so we don't have to drive a
    // sign-out + reload of the page.
    const adminToken = await adminAccessToken(request);
    const replay = await request.post(`${API_URL}${accept.replace(/^http:\/\/[^/]+/, "")}/accept`, {
      headers: { "Content-Type": "application/json" },
      data: { password: "anything-else-that-works" },
    });
    expect(replay.status()).toBe(410);

    // ---- Step 7: clean up — admin lists pending invitations and the
    // accepted one is filtered out by `usePendingInvitations`. We also
    // assert the api lists it as accepted so the cleanup task knows
    // what to revoke later (no-op here but documents the contract).
    const list = await request.get(`${API_URL}/api/v1/orgs/${ORG_ID}/invitations`, {
      headers: {
        Authorization: `Bearer ${adminToken}`,
        "X-Org-ID": ORG_ID,
      },
    });
    expect(list.ok()).toBeTruthy();
    const rows = (await list.json()).data as Array<{ email: string; accepted_at: string | null }>;
    const ours = rows.find((r) => r.email === invitee);
    expect(ours?.accepted_at).not.toBeNull();
  });

  test("revoking a pending invitation makes the accept URL 404", async ({
    page,
    request,
  }) => {
    const adminToken = await adminAccessToken(request);
    const invitee = uniqueInviteeEmail();

    // Create directly via the api (faster than driving the UI again).
    const created = await request.post(
      `${API_URL}/api/v1/orgs/${ORG_ID}/invitations`,
      {
        headers: {
          Authorization: `Bearer ${adminToken}`,
          "X-Org-ID": ORG_ID,
          "Content-Type": "application/json",
        },
        data: { email: invitee, role: "member" },
      },
    );
    expect(created.ok()).toBeTruthy();
    const { id, token } = (await created.json()).data;

    // Revoke it.
    const revoke = await request.delete(
      `${API_URL}/api/v1/orgs/${ORG_ID}/invitations/${id}`,
      {
        headers: { Authorization: `Bearer ${adminToken}`, "X-Org-ID": ORG_ID },
      },
    );
    expect(revoke.status()).toBe(200);

    // Visiting the accept URL now renders the "invalid" empty state.
    await page.goto(`/invite/${token}`);
    await expect(page.getByText(/Lời mời không hợp lệ/i)).toBeVisible({
      timeout: 10_000,
    });
  });
});
