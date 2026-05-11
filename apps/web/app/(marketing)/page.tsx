/**
 * Public landing page — `/`.
 *
 * Sections:
 *   1. Hero — proposition + primary CTA.
 *   2. Modules grid — the 14 product modules organised into 3 buckets
 *      (pre-construction, in-flight, close-out) so a first-time visitor
 *      can map their problem to a module without reading every name.
 *   3. Why-VN strip — 3 short value props specific to the local market.
 *   4. Closing CTA + secondary nav.
 *
 * No images yet — the marketing surface launches with type + colour
 * blocks. A future asset pass adds module screenshots; the layout is
 * designed so dropping them into each `<ModuleCard>` is a one-line
 * change.
 */

import Link from "next/link";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { supabaseServer } from "@/lib/supabase-server";


// One source of truth for the module catalogue — the keys also exist
// in `marketing.modules.<key>` in both locale files. Adding a module
// means appending here + adding two i18n keys; the page picks it up
// automatically.
const MODULE_BUCKETS = [
  {
    key: "pre",
    modules: ["winwork", "bidradar", "costpulse", "drawbridge"],
  },
  {
    key: "live",
    modules: ["pulse", "siteeye", "schedulepilot", "submittals", "dailylog"],
  },
  {
    key: "close",
    modules: ["handover", "punchlist", "changeorder", "codeguard"],
  },
] as const;


export default async function MarketingHome() {
  // Logged-in users → bounce to /winwork. The redirect lives on the
  // landing page (not the layout) so /docs/api, /pricing, /about stay
  // accessible to signed-in users — they might want to share a link.
  // Wrapped in try/catch because the marketing surface MUST render
  // even when Supabase env is missing (dev-without-auth setup).
  try {
    const supabase = await supabaseServer();
    const {
      data: { user },
    } = await supabase.auth.getUser();
    if (user) {
      redirect("/winwork");
    }
  } catch {
    // No-op — render the landing page in the cold path.
  }

  const t = await getTranslations("marketing");

  return (
    <>
      {/* Hero. Type-driven; no hero illustration yet. */}
      <section className="border-b border-slate-200">
        <div className="mx-auto max-w-6xl px-6 py-20 sm:py-28">
          <p className="mb-4 inline-block rounded-full border border-slate-300 px-3 py-1 text-xs font-medium uppercase tracking-wide text-slate-600">
            {t("hero.eyebrow")}
          </p>
          <h1 className="max-w-3xl text-4xl font-semibold leading-tight tracking-tight sm:text-5xl">
            {t("hero.title")}
          </h1>
          <p className="mt-5 max-w-2xl text-lg leading-relaxed text-slate-600">
            {t("hero.subtitle")}
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link
              href="/signup"
              className="rounded-md bg-slate-900 px-5 py-2.5 text-sm font-medium text-white transition hover:bg-slate-800"
            >
              {t("hero.cta_primary")}
            </Link>
            <Link
              href="/pricing"
              className="rounded-md border border-slate-300 px-5 py-2.5 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
            >
              {t("hero.cta_secondary")}
            </Link>
          </div>
        </div>
      </section>

      {/* Modules grid — bucketed by lifecycle phase. */}
      <section className="mx-auto max-w-6xl px-6 py-20">
        <h2 className="text-2xl font-semibold tracking-tight">
          {t("modules.title")}
        </h2>
        <p className="mt-2 max-w-2xl text-sm text-slate-600">
          {t("modules.subtitle")}
        </p>

        <div className="mt-12 space-y-12">
          {MODULE_BUCKETS.map((bucket) => (
            <div key={bucket.key}>
              <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                {t(`modules.bucket.${bucket.key}.title`)}
              </h3>
              <p className="mt-1 max-w-2xl text-sm text-slate-600">
                {t(`modules.bucket.${bucket.key}.subtitle`)}
              </p>
              <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                {bucket.modules.map((m) => (
                  <article
                    key={m}
                    className="rounded-lg border border-slate-200 bg-slate-50 p-4 transition hover:border-slate-300 hover:bg-white"
                  >
                    <h4 className="text-sm font-semibold tracking-tight text-slate-900">
                      {t(`modules.${m}.name`)}
                    </h4>
                    <p className="mt-1.5 text-xs leading-relaxed text-slate-600">
                      {t(`modules.${m}.tagline`)}
                    </p>
                  </article>
                ))}
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Why-VN strip. Short, opinionated, market-specific. */}
      <section className="border-t border-slate-200 bg-slate-50">
        <div className="mx-auto max-w-6xl px-6 py-20">
          <h2 className="text-2xl font-semibold tracking-tight">
            {t("why.title")}
          </h2>
          <div className="mt-10 grid gap-8 sm:grid-cols-3">
            {(["local", "ai", "open"] as const).map((k) => (
              <div key={k}>
                <h3 className="text-sm font-semibold tracking-tight text-slate-900">
                  {t(`why.${k}.title`)}
                </h3>
                <p className="mt-2 text-sm leading-relaxed text-slate-600">
                  {t(`why.${k}.body`)}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Closing CTA. */}
      <section className="border-t border-slate-200">
        <div className="mx-auto max-w-3xl px-6 py-20 text-center">
          <h2 className="text-3xl font-semibold tracking-tight">
            {t("cta.title")}
          </h2>
          <p className="mt-4 text-base text-slate-600">{t("cta.subtitle")}</p>
          <div className="mt-8 flex justify-center gap-3">
            <Link
              href="/signup"
              className="rounded-md bg-slate-900 px-6 py-3 text-sm font-medium text-white transition hover:bg-slate-800"
            >
              {t("cta.primary")}
            </Link>
            <a
              href="mailto:hello@aec-platform.vn"
              className="rounded-md border border-slate-300 px-6 py-3 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
            >
              {t("cta.secondary")}
            </a>
          </div>
        </div>
      </section>
    </>
  );
}
