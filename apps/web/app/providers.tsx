"use client";
import { QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { useState, type ReactNode } from "react";

import { makeQueryClient } from "@/lib/query-client";
import { SessionCtx, type SessionContext } from "@/lib/auth-context";

interface ProvidersProps {
  children: ReactNode;
  session: SessionContext;
  locale: string;
  messages: Record<string, unknown>;
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
