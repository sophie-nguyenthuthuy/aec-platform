"use client";

import { useTranslations } from "next-intl";
import { useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import Link from "next/link";

import { LocaleSwitcher } from "@/components/LocaleSwitcher";
import { supabaseBrowser } from "@/lib/supabase-browser";

/**
 * Email/password sign-in. Strings come from `marketing.auth.login.*`
 * via `useTranslations` so an EN partner clicking through from the
 * marketing landing doesn't hit a Vietnamese form mid-evaluation.
 *
 * The locale-switcher component (top-right) lets either language
 * toggle without leaving the page; the marketing pages and dashboard
 * each have their own switcher already, but this auth surface
 * historically had none — partners arriving via a localised link
 * couldn't change locale until they were inside the app.
 */
export default function LoginPage() {
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next") || "/";
  const t = useTranslations("marketing.auth");

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    const supabase = supabaseBrowser();
    const { error: signInError } = await supabase.auth.signInWithPassword({
      email,
      password,
    });
    setSubmitting(false);
    if (signInError) {
      // Supabase error messages come back in English — they're surfaced
      // verbatim because translating them would require a fragile error-
      // code → key map and the user can paste them into a search engine.
      setError(signInError.message);
      return;
    }
    // Use `replace` so the back button doesn't return to /login.
    router.replace(next);
    // `refresh` so the server components re-run with the new auth cookie.
    router.refresh();
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 px-4">
      {/* Locale switcher — top-right, fixed-position, available
          regardless of the form's vertical centering. Auth pages
          have no nav row, so this is the only escape hatch for a
          user who wants the OTHER locale. */}
      <div className="fixed right-4 top-4 z-10">
        <LocaleSwitcher />
      </div>
      <form
        onSubmit={onSubmit}
        className="w-full max-w-sm space-y-5 rounded-lg border border-slate-200 bg-white p-6 shadow-sm"
      >
        <div>
          <h1 className="text-xl font-semibold text-slate-900">AEC Platform</h1>
          <p className="text-sm text-slate-600">{t("login.subtitle")}</p>
        </div>

        <div className="space-y-3">
          <label className="block">
            <span className="block text-xs font-medium text-slate-700">
              {t("email_label")}
            </span>
            <input
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-500"
            />
          </label>

          <label className="block">
            <span className="block text-xs font-medium text-slate-700">
              {t("password_label")}
            </span>
            <input
              type="password"
              required
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-500"
            />
          </label>
        </div>

        {error ? (
          <div className="rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">{error}</div>
        ) : null}

        <button
          type="submit"
          disabled={submitting}
          className="w-full rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {submitting ? t("login.submitting") : t("login.submit")}
        </button>

        <p className="text-center text-xs text-slate-500">
          <Link href="/forgot-password" className="text-slate-700 hover:underline">
            {t("login.forgot_password")}
          </Link>
        </p>
      </form>
    </div>
  );
}
