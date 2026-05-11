"use client";

import { useLocale } from "next-intl";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Globe } from "lucide-react";


/**
 * Tiny VI/EN toggle for surfaces that don't have one (auth pages).
 *
 * Writes the chosen locale to the `NEXT_LOCALE` cookie (read by
 * `i18n/request.ts` on the next request) and refreshes the route so
 * server components re-resolve their translations against the new
 * cookie value.
 *
 * Why this is its OWN component (not a shared one with the marketing
 * layout's nav switcher): the marketing landing's switcher is part
 * of a horizontal nav row; auth pages have no nav. Wrapping a
 * standalone two-button widget that lives at top-right of the
 * viewport and doesn't depend on a parent layout. ~30 LOC, no
 * sharing cost.
 *
 * Cookie path `/` so the choice persists across the marketing
 * surface, the auth pages, and the dashboard (one user, one locale
 * preference). 1-year max-age — long enough that returning users
 * don't have to re-pick, short enough that abandoned browsers
 * eventually fall back to the default.
 */


const SUPPORTED = [
  { code: "vi", label: "Tiếng Việt" },
  { code: "en", label: "English" },
] as const;


export function LocaleSwitcher() {
  const router = useRouter();
  const current = useLocale();
  const [pending, setPending] = useState(false);

  function setLocale(code: "vi" | "en") {
    if (code === current || pending) return;
    setPending(true);

    // 1-year max-age, path=/, no httpOnly (we need to read it from
    // server components AND let the user clear it client-side).
    // SameSite=Lax keeps the cookie out of cross-site request-forgery
    // contexts while preserving same-site-link navigation.
    const oneYear = 60 * 60 * 24 * 365;
    document.cookie =
      `NEXT_LOCALE=${code}; path=/; max-age=${oneYear}; samesite=lax`;

    // `router.refresh()` re-runs the server components for the
    // current route. The page re-renders with the new cookie's
    // translations without a full page reload — preserves form
    // state on auth pages (a half-typed email survives the toggle).
    router.refresh();
    // Reset the pending state shortly after the refresh; the
    // refresh itself doesn't return a promise we can await
    // reliably across Next.js versions.
    setTimeout(() => setPending(false), 300);
  }

  return (
    <div
      role="group"
      aria-label="Language"
      className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white p-0.5 text-xs"
    >
      <Globe size={12} className="ml-1 mr-0.5 text-slate-400" aria-hidden />
      {SUPPORTED.map((opt) => {
        const active = opt.code === current;
        return (
          <button
            key={opt.code}
            type="button"
            onClick={() => setLocale(opt.code)}
            disabled={pending || active}
            aria-pressed={active}
            className={`rounded px-2 py-0.5 transition ${
              active
                ? "bg-slate-900 text-white"
                : "text-slate-600 hover:bg-slate-100"
            } disabled:cursor-default`}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}
