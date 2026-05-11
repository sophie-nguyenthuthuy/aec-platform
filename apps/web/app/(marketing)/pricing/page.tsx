/**
 * Pricing page — `/pricing`.
 *
 * Three tiers — Starter / Growth / Scale — bound to the existing
 * `subscription_tier` column on `organizations`. Numbers are placeholder;
 * the structure (per-user, per-month, with annual-pay discount) is
 * what we want to lock so a future pricing experiment doesn't have to
 * redesign the page.
 *
 * Order intentional: most-popular tier in the centre with a visual
 * pop so the eye lands there first. Faux-modal upgrade CTAs all
 * route to /signup; real billing wiring is its own ticket.
 */

import Link from "next/link";
import { getTranslations } from "next-intl/server";


// Visible per-tier feature set. The boolean signals whether the feature
// is INCLUDED at this tier (bullet) vs ABSENT (greyed). Mirrors what
// `subscription_tier` actually gates server-side, so a marketing claim
// can't drift from product reality without somebody noticing.
type FeatureRow = { key: string; tiers: [boolean, boolean, boolean] };

const FEATURES: FeatureRow[] = [
  { key: "modules_all", tiers: [true, true, true] },
  { key: "users_5", tiers: [true, false, false] },
  { key: "users_25", tiers: [false, true, false] },
  { key: "users_unlimited", tiers: [false, false, true] },
  { key: "ai_assistant", tiers: [true, true, true] },
  { key: "api_keys", tiers: [false, true, true] },
  { key: "webhooks", tiers: [false, true, true] },
  { key: "audit_export", tiers: [false, true, true] },
  { key: "sla_8h", tiers: [false, true, false] },
  { key: "sla_2h", tiers: [false, false, true] },
  { key: "dedicated_csm", tiers: [false, false, true] },
];


const TIERS = ["starter", "growth", "scale"] as const;


export default async function PricingPage() {
  const t = await getTranslations("marketing.pricing");

  return (
    <section className="mx-auto max-w-6xl px-6 py-20">
      <header className="mx-auto max-w-2xl text-center">
        <h1 className="text-4xl font-semibold tracking-tight">{t("title")}</h1>
        <p className="mt-4 text-base text-slate-600">{t("subtitle")}</p>
      </header>

      <div className="mt-14 grid gap-6 lg:grid-cols-3">
        {TIERS.map((tier, idx) => {
          const popular = tier === "growth";
          return (
            <article
              key={tier}
              className={[
                "flex flex-col rounded-xl border p-6",
                popular
                  ? "border-slate-900 bg-slate-900 text-white shadow-lg"
                  : "border-slate-200 bg-white",
              ].join(" ")}
            >
              {popular ? (
                <span className="mb-3 inline-block w-fit rounded-full bg-white/15 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide text-white">
                  {t("popular")}
                </span>
              ) : null}
              <h2
                className={[
                  "text-xl font-semibold tracking-tight",
                  popular ? "text-white" : "text-slate-900",
                ].join(" ")}
              >
                {t(`tier.${tier}.name`)}
              </h2>
              <p
                className={[
                  "mt-2 text-sm",
                  popular ? "text-white/80" : "text-slate-600",
                ].join(" ")}
              >
                {t(`tier.${tier}.tagline`)}
              </p>
              <div className="mt-6 flex items-baseline gap-1">
                <span className="text-4xl font-semibold tracking-tight">
                  {t(`tier.${tier}.price`)}
                </span>
                <span
                  className={[
                    "text-sm",
                    popular ? "text-white/70" : "text-slate-500",
                  ].join(" ")}
                >
                  {t("per_user_month")}
                </span>
              </div>
              <Link
                href="/signup"
                className={[
                  "mt-6 inline-flex items-center justify-center rounded-md px-4 py-2.5 text-sm font-medium transition",
                  popular
                    ? "bg-white text-slate-900 hover:bg-slate-100"
                    : "bg-slate-900 text-white hover:bg-slate-800",
                ].join(" ")}
              >
                {t(`tier.${tier}.cta`)}
              </Link>
              <ul className="mt-6 space-y-2 text-sm">
                {FEATURES.filter((f) => f.tiers[idx]).map((f) => (
                  <li
                    key={f.key}
                    className={[
                      "flex items-start gap-2",
                      popular ? "text-white/90" : "text-slate-700",
                    ].join(" ")}
                  >
                    <span aria-hidden className="mt-0.5">✓</span>
                    <span>{t(`feature.${f.key}`)}</span>
                  </li>
                ))}
              </ul>
            </article>
          );
        })}
      </div>

      <footer className="mt-12 border-t border-slate-200 pt-8 text-center text-sm text-slate-600">
        {t.rich("footer_note", {
          contact: (chunks) => (
            <a
              href="mailto:sales@aec-platform.vn"
              className="text-slate-900 underline"
            >
              {chunks}
            </a>
          ),
        })}
      </footer>
    </section>
  );
}
