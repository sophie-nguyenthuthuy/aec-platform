"use client";

import { useState } from "react";

import { supabaseBrowser } from "@/lib/supabase-browser";


// Supabase calls the provider slug `azure` for Microsoft Entra ID
// (formerly Azure AD); the UI says "Microsoft" because no end user
// thinks of their work account as "Azure".
//
// Google Workspace and personal Google accounts share the same `google`
// provider; the workspace restriction is enforced server-side via the
// Supabase project's auth config (Allowed Workspace Domains), so the
// frontend doesn't need to differentiate.
type ProviderSlug = "google" | "azure";

interface ProviderConfig {
  slug: ProviderSlug;
  label: string;
  icon: JSX.Element;
}

const PROVIDERS: ProviderConfig[] = [
  {
    slug: "google",
    label: "Đăng nhập với Google Workspace",
    icon: <GoogleLogo />,
  },
  {
    slug: "azure",
    label: "Đăng nhập với Microsoft",
    icon: <MicrosoftLogo />,
  },
];


/**
 * OAuth sign-in buttons rendered above the email/password form.
 *
 * Why two distinct buttons rather than a generic "SSO" picker:
 *   * SOE customers typically standardise on one of the two
 *     (Microsoft 365 dominates State-owned enterprises; Google
 *     Workspace shows up in private-sector EPCs). Showing both is
 *     friction-free for individual users.
 *   * A single labelled "SSO" button would force a sub-menu and an
 *     extra click on the most-trafficked page in the app.
 *
 * The "next" prop carries through to the OAuth callback so the user
 * lands where they meant to go after the round-trip. Without this,
 * deep links bookmarked behind a session timeout drop the user at /
 * after re-auth — confusing and we already pay for the same plumbing
 * for password sign-in.
 */
export function SsoButtons({ next }: { next?: string }) {
  const [pending, setPending] = useState<ProviderSlug | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function start(provider: ProviderSlug) {
    setError(null);
    setPending(provider);
    const supabase = supabaseBrowser();

    // Build the absolute callback URL — Supabase requires this exact
    // string to be in the project's allowed-redirect list (Auth →
    // URL configuration). Same string lives in deploy/STEPS.md.
    const callbackUrl = new URL("/auth/callback", window.location.origin);
    if (next) callbackUrl.searchParams.set("next", next);

    const { error: oauthError } = await supabase.auth.signInWithOAuth({
      provider,
      options: {
        redirectTo: callbackUrl.toString(),
        // Force the consent screen on Microsoft so users can pick the
        // right work account in households / shared devices. Google
        // remembers the previous choice — let it stay smooth.
        ...(provider === "azure" ? { queryParams: { prompt: "select_account" } } : {}),
      },
    });

    if (oauthError) {
      setError(oauthError.message);
      setPending(null);
    }
    // On success, Supabase navigates away — no need to clear pending.
  }

  return (
    <div className="space-y-2">
      {PROVIDERS.map((p) => (
        <button
          key={p.slug}
          type="button"
          onClick={() => start(p.slug)}
          disabled={pending !== null}
          className="flex w-full items-center justify-center gap-2 rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {p.icon}
          <span>
            {pending === p.slug ? "Đang chuyển hướng…" : p.label}
          </span>
        </button>
      ))}

      {error && (
        <p className="text-xs text-rose-600" role="alert">
          {error}
        </p>
      )}

      <div className="my-3 flex items-center gap-3 text-[11px] uppercase tracking-wide text-slate-400">
        <span className="h-px flex-1 bg-slate-200" />
        hoặc
        <span className="h-px flex-1 bg-slate-200" />
      </div>
    </div>
  );
}


// ---------- Inline brand logos ----------
// Embedded as SVG to avoid a network round-trip per render + so the
// button stays usable when the user is offline (a common "save me from
// login" scenario on flaky Vietnamese mobile networks).


function GoogleLogo() {
  return (
    <svg width="16" height="16" viewBox="0 0 48 48" aria-hidden>
      <path
        fill="#FFC107"
        d="M43.6 20.5H42V20H24v8h11.3c-1.6 4.7-6.1 8-11.3 8-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.1 8 3l5.7-5.7C34.5 6.2 29.5 4 24 4 13 4 4 13 4 24s9 20 20 20 20-9 20-20c0-1.2-.1-2.4-.4-3.5z"
      />
      <path
        fill="#FF3D00"
        d="M6.3 14.7l6.6 4.8C14.7 16 19 13 24 13c3.1 0 5.8 1.1 8 3l5.7-5.7C34.5 6.2 29.5 4 24 4c-7.7 0-14.4 4.4-17.7 10.7z"
      />
      <path
        fill="#4CAF50"
        d="M24 44c5.4 0 10.3-2.1 14-5.5l-6.5-5.3c-2 1.4-4.5 2.3-7.5 2.3-5.2 0-9.6-3.3-11.2-8l-6.5 5C9.4 39.5 16.1 44 24 44z"
      />
      <path
        fill="#1976D2"
        d="M43.6 20.5H42V20H24v8h11.3c-.8 2.3-2.3 4.3-4.2 5.7l6.5 5.3c-.5.5 7.4-5.4 7.4-15 0-1.2-.1-2.4-.4-3.5z"
      />
    </svg>
  );
}


function MicrosoftLogo() {
  return (
    <svg width="16" height="16" viewBox="0 0 23 23" aria-hidden>
      <path fill="#F25022" d="M1 1h10v10H1z" />
      <path fill="#7FBA00" d="M12 1h10v10H12z" />
      <path fill="#00A4EF" d="M1 12h10v10H1z" />
      <path fill="#FFB900" d="M12 12h10v10H12z" />
    </svg>
  );
}
