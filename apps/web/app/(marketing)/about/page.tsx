/**
 * About page — `/about`.
 *
 * Three sections:
 *   1. Story — short narrative, founder voice. Why this exists.
 *   2. Numbers — projects on the platform, modules shipped, etc.
 *      Hard-coded today; a future enhancement reads them from the
 *      org/projects rollup table.
 *   3. Contact — email + (future) office address.
 *
 * Kept text-heavy on purpose: AEC buyers in VN read the about page
 * before they trust an SaaS — typical journey is "land → about →
 * pricing → demo". Don't optimize this page for skim.
 */

import { getTranslations } from "next-intl/server";


const NUMBERS = [
  { key: "modules", value: "14" },
  { key: "languages", value: "VI · EN" },
  { key: "regions", value: "VN" },
  { key: "version", value: "0.1" },
] as const;


export default async function AboutPage() {
  const t = await getTranslations("marketing.about");

  return (
    <section className="mx-auto max-w-3xl px-6 py-20">
      <header>
        <h1 className="text-4xl font-semibold tracking-tight">{t("title")}</h1>
        <p className="mt-4 text-base text-slate-600">{t("subtitle")}</p>
      </header>

      {/* Story */}
      <div className="mt-12 space-y-5 text-base leading-relaxed text-slate-700">
        <p>{t("story.p1")}</p>
        <p>{t("story.p2")}</p>
        <p>{t("story.p3")}</p>
      </div>

      {/* Numbers strip */}
      <dl className="mt-14 grid grid-cols-2 gap-6 rounded-xl border border-slate-200 bg-slate-50 p-6 sm:grid-cols-4">
        {NUMBERS.map((n) => (
          <div key={n.key}>
            <dt className="text-xs uppercase tracking-wide text-slate-500">
              {t(`numbers.${n.key}`)}
            </dt>
            <dd className="mt-1 text-2xl font-semibold tracking-tight text-slate-900">
              {n.value}
            </dd>
          </div>
        ))}
      </dl>

      {/* Contact */}
      <div className="mt-14">
        <h2 className="text-xl font-semibold tracking-tight">
          {t("contact.title")}
        </h2>
        <p className="mt-3 text-sm text-slate-600">{t("contact.body")}</p>
        <ul className="mt-4 space-y-1.5 text-sm text-slate-700">
          <li>
            {t("contact.email_label")}:{" "}
            <a
              href="mailto:hello@aec-platform.vn"
              className="text-slate-900 underline"
            >
              hello@aec-platform.vn
            </a>
          </li>
          <li>
            {t("contact.sales_label")}:{" "}
            <a
              href="mailto:sales@aec-platform.vn"
              className="text-slate-900 underline"
            >
              sales@aec-platform.vn
            </a>
          </li>
        </ul>
      </div>
    </section>
  );
}
