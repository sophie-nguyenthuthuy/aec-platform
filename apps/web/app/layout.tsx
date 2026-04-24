import type { Metadata } from "next";
import { getLocale, getMessages } from "next-intl/server";
import type { ReactNode } from "react";

import { Providers } from "./providers";
import "./globals.css";

export const metadata: Metadata = {
  title: "AEC Platform",
  description: "AI-powered platform for architecture, engineering, and construction",
};

export default async function RootLayout({ children }: { children: ReactNode }) {
  const locale = await getLocale();
  const messages = await getMessages();

  const session = {
    token: "dev-token",
    orgId: "00000000-0000-0000-0000-000000000000",
    userId: "00000000-0000-0000-0000-000000000000",
    locale: locale as "vi" | "en",
  };

  return (
    <html lang={locale}>
      <body>
        <Providers session={session} locale={locale} messages={messages as Record<string, unknown>}>
          {children}
        </Providers>
      </body>
    </html>
  );
}
