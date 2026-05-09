/**
 * Marketing chrome — header + footer wrapping `/`, `/pricing`, `/about`.
 *
 * Why a route group (not a normal layout):
 *   The (marketing) directory is a Next.js route group, so its `layout.tsx`
 *   wraps the marketing pages WITHOUT prefixing the URL. `/pricing` stays
 *   `/pricing` even though the file is at `app/(marketing)/pricing/`.
 *
 * Why server-side `supabaseServer()`:
 *   We want logged-in users landing on `/` to bounce straight to
 *   `/winwork` rather than read marketing copy. Doing that on the server
 *   avoids the flash-of-marketing-page on a client redirect.
 *
 * `dynamic = "force-dynamic"` because the parent root layout already
 * pulls cookies; without this Next would try to prerender and trip on
 * the runtime supabase env.
 */

import Link from "next/link";
import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";


export const dynamic = "force-dynamic";

// NOTE: this layout used to bounce logged-in users to /winwork. We
// pulled that behaviour into `(marketing)/page.tsx` (landing only)
// so /docs/api, /docs/webhooks, /pricing, /about stay readable for
// both signed-in users and unauthenticated visitors. A logged-in dev
// reading API docs shouldn't have to sign out first.

export default async function MarketingLayout({
  children,
}: {
  children: ReactNode;
}) {
  const t = await getTranslations("marketing");

  return (
    <div className="min-h-screen bg-white text-slate-900">
      <header className="sticky top-0 z-10 border-b border-slate-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <Link href="/" className="flex items-center gap-2">
            <span className="inline-block h-6 w-6 rounded bg-slate-900" />
            <span className="text-base font-semibold tracking-tight">
              AEC Platform
            </span>
          </Link>
          <nav className="flex items-center gap-3 text-sm sm:gap-6">
            {/* Pricing / Docs / About hidden on mobile — five links + a
                CTA button overflow the 375px header. The "Try free"
                CTA stays so a mobile visitor still has the primary
                conversion path. To find pricing/docs on mobile, the
                user scrolls to the footer (which keeps every link). */}
            <Link
              href="/pricing"
              className="hidden text-slate-600 hover:text-slate-900 sm:inline"
            >
              {t("nav.pricing")}
            </Link>
            <Link
              href="/docs/api"
              className="hidden text-slate-600 hover:text-slate-900 sm:inline"
            >
              {t("nav.docs")}
            </Link>
            <Link
              href="/about"
              className="hidden text-slate-600 hover:text-slate-900 sm:inline"
            >
              {t("nav.about")}
            </Link>
            <Link
              href="/login"
              className="text-slate-600 hover:text-slate-900"
            >
              {t("nav.login")}
            </Link>
            <Link
              href="/signup"
              className="rounded-md bg-slate-900 px-3 py-1.5 text-white transition hover:bg-slate-800"
            >
              {t("nav.signup")}
            </Link>
          </nav>
        </div>
      </header>
      <main>{children}</main>
      <footer className="mt-24 border-t border-slate-200 bg-slate-50">
        <div className="mx-auto flex max-w-6xl flex-col items-start justify-between gap-4 px-6 py-10 text-xs text-slate-500 sm:flex-row sm:items-center">
          <p>© {new Date().getFullYear()} AEC Platform. {t("footer.tagline")}</p>
          <div className="flex flex-wrap gap-4">
            <Link href="/pricing" className="hover:text-slate-700">
              {t("nav.pricing")}
            </Link>
            <Link href="/docs/api" className="hover:text-slate-700">
              {t("nav.docs")}
            </Link>
            <Link href="/docs/webhooks" className="hover:text-slate-700">
              {t("footer.webhooks")}
            </Link>
            <Link href="/about" className="hover:text-slate-700">
              {t("nav.about")}
            </Link>
            <a
              href="mailto:hello@aec-platform.vn"
              className="hover:text-slate-700"
            >
              hello@aec-platform.vn
            </a>
          </div>
        </div>
      </footer>
    </div>
  );
}
