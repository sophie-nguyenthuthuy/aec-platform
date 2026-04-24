import { getRequestConfig } from "next-intl/server";

const SUPPORTED = ["vi", "en"] as const;
type Locale = (typeof SUPPORTED)[number];

export default getRequestConfig(async () => {
  const locale: Locale = "vi";
  return {
    locale,
    messages: (await import(`./messages/${locale}.json`)).default,
  };
});
