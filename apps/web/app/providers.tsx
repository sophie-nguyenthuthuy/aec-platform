"use client";
import { QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider, type AbstractIntlMessages } from "next-intl";
import { useState, type ReactNode } from "react";

import { makeQueryClient } from "@/lib/query-client";
import { SessionCtx, type SessionContext } from "@/lib/auth-context";

interface ProvidersProps {
  children: ReactNode;
  /** null on public pages (e.g. /login). Authenticated pages assert via
   *  `useSession()` which throws if session is missing. */
  session: SessionContext | null;
  locale: string;
  messages: AbstractIntlMessages;
}

export function Providers({ children, session, locale, messages }: ProvidersProps) {
  const [client] = useState(() => makeQueryClient());
  return (
    <SessionCtx.Provider value={session}>
      <NextIntlClientProvider locale={locale} messages={messages}>
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      </NextIntlClientProvider>
    </SessionCtx.Provider>
  );
}
