"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { LocaleSwitcher } from "@/components/LocaleSwitcher";
import { supabaseBrowser } from "@/lib/supabase-browser";

/**
 * Self-serve signup. Strings live under `marketing.auth.signup.*` so
 * an EN-clicking partner from `/pricing` lands on an English form
 * rather than the Vietnamese hard-coded copy.
 *
 * Supabase signup behaviour:
 *
 *  * If "Confirm email" is OFF (dev default), `signUp` returns a
 *    populated `session` immediately — we redirect to `/`, where the
 *    layout sees the new user has no orgs and renders the onboarding
 *    "create your org" pane.
 *
 *  * If "Confirm email" is ON (prod default), `session` is null until
 *    the user clicks the verification link. Show "check your email"
 *    and stop.
 *
 *  Either way, the new local DB rows (`users`, `org_members`) are
 *  created on first authenticated `/me/orgs` call by the auto-
 *  provisioner — signup itself only touches Supabase.
 */
export default function SignupPage() {
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next") || "/";
  const t = useTranslations("marketing.auth");

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [needsConfirmation, setNeedsConfirmation] = useState(false);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);

    const supabase = supabaseBrowser();
    const { data, error: signUpError } = await supabase.auth.signUp({
      email,
      password,
    });
    setSubmitting(false);

    if (signUpError) {
      // Supabase error messages come back in English — surfaced
      // verbatim (same rationale as the login page).
      setError(signUpError.message);
      return;
    }

    if (data.session) {
      // Auto-confirmed — go to /, layout will detect no orgs and render
      // the onboarding form.
      router.replace(next);
      router.refresh();
      return;
    }

    // Email confirmation required. Show the "check your inbox" state.
    setNeedsConfirmation(true);
  }

  if (needsConfirmation) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50 px-4">
        <div className="fixed right-4 top-4 z-10">
          <LocaleSwitcher />
        </div>
        <div className="w-full max-w-sm space-y-3 rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
          <h1 className="text-xl font-semibold text-slate-900">
            {t("confirm.title")}
          </h1>
          <p className="text-sm text-slate-600">
            {t.rich("confirm.body", {
              email: () => (
                <span className="font-mono text-xs">{email}</span>
              ),
            })}
          </p>
          <Link
            href="/login"
            className="block rounded-md border border-slate-300 px-3 py-2 text-center text-sm text-slate-700 hover:bg-slate-50"
          >
            {t("confirm.back_to_login")}
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 px-4">
      <div className="fixed right-4 top-4 z-10">
        <LocaleSwitcher />
      </div>
      <form
        onSubmit={onSubmit}
        className="w-full max-w-sm space-y-5 rounded-lg border border-slate-200 bg-white p-6 shadow-sm"
      >
        <div>
          <h1 className="text-xl font-semibold text-slate-900">AEC Platform</h1>
          <p className="text-sm text-slate-600">{t("signup.subtitle")}</p>
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
              {t("signup.password_label")}
            </span>
            <input
              type="password"
              required
              minLength={8}
              autoComplete="new-password"
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
          {submitting ? t("signup.submitting") : t("signup.submit")}
        </button>

        <p className="text-center text-xs text-slate-500">
          {t.rich("signup.have_account", {
            link: (chunks) => (
              <Link
                href="/login"
                className="font-medium text-slate-700 hover:underline"
              >
                {chunks}
              </Link>
            ),
          })}
        </p>
      </form>
    </div>
  );
}
