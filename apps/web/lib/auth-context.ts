"use client";
import { createContext, useContext } from "react";

export interface SessionContext {
  token: string;
  orgId: string;
  userId: string;
  locale: "vi" | "en";
}

export const SessionCtx = createContext<SessionContext | null>(null);

export function useSession(): SessionContext {
  const ctx = useContext(SessionCtx);
  if (!ctx) throw new Error("useSession must be used inside <SessionProvider>");
  return ctx;
}
