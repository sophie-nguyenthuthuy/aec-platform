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

  // Until the real Supabase auth flow lands, the layout seeds a placeholder
  // session. The three AEC_DEV_SESSION_* env vars let local smoke runs inject
  // a real JWT + org so hooks like `useProposal` actually authenticate — see
  // docker-compose.override.yml for the paired api-side dev toggle.
  const session = {
    token: process.env.AEC_DEV_SESSION_TOKEN ?? "dev-token",
    orgId: process.env.AEC_DEV_SESSION_ORG_ID ?? "00000000-0000-0000-0000-000000000000",
    userId: process.env.AEC_DEV_SESSION_USER_ID ?? "00000000-0000-0000-0000-000000000000",
    locale: locale as "vi" | "en",
  };

  return (
    <html lang={locale}>
      <body>
        <Providers session={session} locale={locale} messages={messages}>
          {children}
        </Providers>
      </body>
    </html>
  );
}
