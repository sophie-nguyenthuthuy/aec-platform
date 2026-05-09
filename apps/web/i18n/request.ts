import { cookies } from "next/headers";
import { getRequestConfig } from "next-intl/server";


const SUPPORTED = ["vi", "en"] as const;
type Locale = (typeof SUPPORTED)[number];

const DEFAULT_LOCALE: Locale = "vi";

/**
 * Cookie name partners' browsers persist the chosen locale under.
 * Standard convention used across next-intl + i18next ecosystems —
 * keeping the same name means a future migration to one of those
 * libs reuses the existing cookie without forcing every user to
 * re-pick.
 *
 * Public on the cookie (no httpOnly): the locale switcher writes from
 * client-side JS via document.cookie, so server-only would defeat
 * the use case. The value space is closed (`vi`/`en`) so an attacker
 * setting a junk locale just falls back to the default — no XSS or
 * injection vector.
 */
export const LOCALE_COOKIE = "NEXT_LOCALE";


function isSupported(value: string | undefined): value is Locale {
  return value !== undefined && (SUPPORTED as readonly string[]).includes(value);
}


/**
 * Read the user's chosen locale.
 *
 * Priority:
 *   1. `NEXT_LOCALE` cookie if set + supported (the locale switcher's
 *      output — explicit user choice).
 *   2. Default `vi` — the original platform locale, preserved as the
 *      fallback for any user who hasn't picked.
 *
 * `Accept-Language` negotiation is intentionally NOT in this chain.
 * Most VN-residing browsers send `vi-VN` regardless of UI language;
 * negotiating off the header would route them to VI even when they
 * prefer EN. Explicit user choice via the switcher is the only signal
 * we trust.
 */
export default getRequestConfig(async () => {
  const cookieStore = await cookies();
  const cookieLocale = cookieStore.get(LOCALE_COOKIE)?.value;

  const locale: Locale = isSupported(cookieLocale) ? cookieLocale : DEFAULT_LOCALE;

  return {
    locale,
    messages: (await import(`./messages/${locale}.json`)).default,
  };
});
