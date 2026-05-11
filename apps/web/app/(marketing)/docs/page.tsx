/**
 * `/docs` — partner-docs hub.
 *
 * Index page that lists every developer-doc sub-page. Without it,
 * a partner navigating to `/docs/` (which a lot of people do
 * reflexively) hits Next's 404 default. The hub is also the place
 * the marketing nav's "Docs" link points to — clicking it from the
 * landing page should land here, not on `/docs/api` arbitrarily.
 *
 * Section grid pattern matches the `/admin` hub built in I1 +
 * the `/codeguard` and `/costpulse` hub pages — visual consistency
 * across hub-style pages in the app.
 */

import Link from "next/link";
import { getTranslations } from "next-intl/server";
import { Activity, BookOpen, Code2, Webhook } from "lucide-react";


// One source of truth for what's under `/docs`. Adding a new doc
// page = one entry here + the page file + matching i18n keys at
// `marketing.docs.hub.pages.<key>.{title,description}` in both locale
// files. Order picks expected frequency: API reference and webhook
// docs are the daily-driver surfaces; the event catalog is a
// reference table; ops docs are admin-side.
const DOC_PAGES = [
  { key: "api", href: "/docs/api", icon: Code2 },
  { key: "webhooks", href: "/docs/webhooks", icon: Webhook },
  { key: "events", href: "/docs/webhooks/events", icon: BookOpen },
  { key: "ops", href: "/docs/ops", icon: Activity },
] as const;


export default async function DocsHubPage() {
  const t = await getTranslations("marketing.docs.hub");

  return (
    <section className="mx-auto max-w-4xl px-6 py-16">
      <header className="space-y-3">
        <div className="flex items-center gap-2">
          <BookOpen size={20} className="text-blue-600" />
          <h1 className="text-3xl font-semibold tracking-tight">
            {t("title")}
          </h1>
        </div>
        <p className="max-w-2xl text-base leading-relaxed text-slate-600">
          {t("intro")}
        </p>
        <p className="max-w-2xl text-sm text-slate-500">
          {t.rich("manage_keys_hint", {
            link: (chunks) => (
              <Link
                href="/settings/api-keys"
                className="text-slate-900 underline"
              >
                {chunks}
              </Link>
            ),
            code: (chunks) => (
              <code className="rounded bg-slate-100 px-1 text-xs">
                {chunks}
              </code>
            ),
          })}
        </p>
      </header>

      <div className="mt-12 grid gap-3 sm:grid-cols-2">
        {DOC_PAGES.map((p) => (
          <Link
            key={p.href}
            href={p.href}
            className="block rounded-xl border border-slate-200 bg-white p-5 transition hover:border-blue-300 hover:shadow-sm"
          >
            <div className="flex items-start gap-3">
              <div className="rounded-md bg-slate-100 p-2 text-slate-600">
                <p.icon size={16} aria-hidden />
              </div>
              <div className="min-w-0 flex-1">
                <h2 className="text-base font-semibold text-slate-900">
                  {t(`pages.${p.key}.title`)}
                </h2>
                <p className="mt-1 text-xs leading-relaxed text-slate-600">
                  {t(`pages.${p.key}.description`)}
                </p>
              </div>
            </div>
          </Link>
        ))}
      </div>
    </section>
  );
}
