"use client";
import { createContext, useContext } from "react";

export interface SessionContext {
  token: string;
  orgId: string;
  userId: string;
  email: string;
  locale: "vi" | "en";
  /** All orgs the user belongs to — feeds the org-switcher. */
  orgs: Array<{ id: string; name: string; role: string }>;
}

export const SessionCtx = createContext<SessionContext | null>(null);

/**
 * Throws if used outside an authenticated context. Pages that need to render
 * without a session (e.g. /login) should not call this — they're rendered at
 * a parent layout level that doesn't gate on auth.
 */
export function useSession(): SessionContext {
  const ctx = useContext(SessionCtx);
  if (!ctx) throw new Error("useSession must be used inside <SessionProvider>");
  return ctx;
}

/** Non-throwing variant for pages that may or may not have a session. */
export function useMaybeSession(): SessionContext | null {
  return useContext(SessionCtx);
}
