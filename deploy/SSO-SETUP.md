# SSO setup — Google Workspace + Microsoft (Entra ID)

The login page (`/login`) renders two OAuth buttons above the
email/password form: "Đăng nhập với Google Workspace" and "Đăng nhập
với Microsoft". Both go through Supabase Auth, so the SaaS side has no
JWT signing or token swap to manage — Supabase mints the session, the
app reads the cookie via `@supabase/ssr`.

Until each provider is configured below, clicking a button surfaces
Supabase's `provider is not enabled` error. Surface this to admins
before launch.

---

## 1. Google Workspace

### 1a. Google Cloud project

1. https://console.cloud.google.com → create a new project named
   e.g. `aec-platform-prod`. Existing project is fine if you already
   use Google APIs.
2. APIs & Services → **OAuth consent screen**:
   - **User Type**: Internal (Workspace-only restriction) or External
     (anyone with a Google account). Pick Internal if you want the
     IT admin's "Allowed Workspace Domains" guard-rail.
   - **App name**: `AEC Platform`
   - **User support email**: ops@aec-platform.vn (or yours)
   - **Authorized domains**: `aec-platform.vn`, `supabase.co`
   - Save through every screen — no scope changes needed beyond
     the defaults (email, profile, openid).
3. APIs & Services → **Credentials** → **+ Create credentials** →
   **OAuth client ID**:
   - **Application type**: Web application
   - **Name**: `aec-platform-supabase`
   - **Authorized redirect URIs**: paste the **two** URLs below.
     The first is what Supabase actually calls; the second lets the
     Supabase dashboard's "Test connection" button work.
     ```
     https://<YOUR-PROJECT-REF>.supabase.co/auth/v1/callback
     ```
4. Save. Copy the **Client ID** + **Client secret**.

### 1b. Supabase project

1. Supabase dashboard → your project → **Authentication** →
   **Providers** → **Google**.
2. Toggle **Enable Sign in with Google** ON.
3. Paste the Client ID + Client secret from step 1a-4.
4. (Optional) **Allowed Workspace Domains**: `cty-xay-dung.vn` to
   restrict sign-in to a specific Workspace tenant. Leave blank to
   accept any Google account.
5. **Save**.

### 1c. Redirect-URL allowlist

Supabase → **Authentication** → **URL Configuration** → **Redirect URLs**:

```
https://YOUR-PROJECT.vercel.app/auth/callback
https://YOUR-PROJECT.vercel.app/auth/callback?next=/**
http://localhost:3000/auth/callback
http://localhost:3000/auth/callback?next=/**
```

Without these, Supabase rejects the post-OAuth redirect and the user
lands on a Supabase error page instead of `/`.

---

## 2. Microsoft (Entra ID / Azure AD)

### 2a. Microsoft Entra app registration

1. https://entra.microsoft.com → **Applications** → **App
   registrations** → **+ New registration**.
2. Fields:
   - **Name**: `AEC Platform`
   - **Supported account types**:
     - Pick **Single tenant** if you want only your org's M365
       accounts to sign in (typical SOE customer requirement).
     - Pick **Multitenant** for SaaS multi-customer.
     - Pick **Multitenant + personal accounts** to also accept
       `@outlook.com` / `@hotmail.com`.
   - **Redirect URI**: Web →
     `https://<YOUR-PROJECT-REF>.supabase.co/auth/v1/callback`
3. Register. Copy the **Application (client) ID** and the
   **Directory (tenant) ID** from the overview pane.
4. **Certificates & secrets** → **+ New client secret**:
   - Description: `aec-platform-supabase`
   - Expires: 24 months (set a calendar reminder to rotate)
   - Copy the secret **Value** immediately — Entra hides it after.

### 2b. Supabase project

1. Supabase dashboard → **Authentication** → **Providers** → **Azure**.
2. Toggle **Enable Sign in with Azure** ON.
3. Paste:
   - **Application (client) ID** → step 2a-3
   - **Secret Value** → step 2a-4
   - **Azure Tenant URL**:
     ```
     https://login.microsoftonline.com/<TENANT-ID>/v2.0
     ```
     where `<TENANT-ID>` is the Directory ID from step 2a-3 (or
     `common` for multitenant — but stricter is safer).
4. **Save**.

The redirect URL allowlist from §1c covers both providers — no
duplicate config.

---

## 3. Verify

1. Open `/login` in an incognito window.
2. Click **Đăng nhập với Google Workspace** — should redirect to
   Google's consent screen. Approve → land on `/` with a session.
3. Sign out (header dropdown). Click **Đăng nhập với Microsoft** —
   same flow against Entra.

If you get `provider is not enabled`: re-check Supabase → Providers
toggle. If you get `redirect_uri_mismatch`: the URL Configuration
allowlist (§1c) is missing the exact callback URL.

---

## 4. Membership provisioning

OAuth sign-in creates a Supabase user but does **not** auto-attach
that user to an `organizations` row. By default a new SSO user lands
on the empty onboarding flow at `/onboarding/create-org` because they
have no membership yet.

To pre-provision an organisation membership for known emails (e.g.
the IT admin pastes `nguyen@cty-x.vn` into a Members list before
that user has logged in), use the existing invitations flow:

  * Settings → Thành viên → "Mời thành viên" → enter email + role
  * The first time the user signs in via SSO with that email, the
    onboarding redirect picks up the pending invitation and binds
    the SSO `auth.users.id` to the membership row.

There is **no separate SSO membership flow** — it reuses the same
invitations table to keep the membership audit-trail single-sourced.
