/**
 * Banner that flags a docs page as Vietnamese-canonical with the
 * English translation in progress. Renders only when the active
 * locale is `en` — VI readers see no banner.
 *
 * Used on `/docs/api` and `/docs/webhooks` until the full string
 * extraction lands. The smaller pages (`/docs` index +
 * `/docs/webhooks/events`) are fully i18n'd; for the large pages
 * (1100+ lines combined) the banner is a stopgap that's honest about
 * the state — better than EN partners scrolling into VI paragraphs
 * mid-section without warning.
 */

import { getTranslations, getLocale } from "next-intl/server";


export async function TranslationNotice() {
  const locale = await getLocale();
  if (locale === "vi") return null;

  const t = await getTranslations("marketing.docs.translation_notice");

  return (
    <div className="not-prose mb-6 rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
      <p className="font-semibold">{t("title")}</p>
      <p className="mt-1 text-xs leading-relaxed text-amber-800">
        {t("body")}
      </p>
    </div>
  );
}
