import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { SessionCtx } from "@/lib/auth-context";

/**
 * Shared harness for hook contract tests.
 *
 * The hooks under test all read `{ token, orgId }` from `useSession()` —
 * so every test wraps in a `<SessionCtx.Provider>`. They also use
 * TanStack Query (`useMutation`, `useQuery`), which needs a
 * `<QueryClientProvider>`. We construct a fresh QueryClient per test so
 * cached results don't bleed between cases.
 *
 * `retry: false` is critical for mutation tests — without it, a mocked
 * fetch that rejects would trigger TanStack's default 3-retry chain,
 * making "did the call happen with X args?" tests slow and racy.
 */
export function makeWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });

  const session = {
    token: "test-token",
    orgId: "00000000-0000-0000-0000-000000000000",
    userId: "00000000-0000-0000-0000-000000000000",
    email: "test@test.local",
    locale: "vi" as const,
    orgs: [],
  };

  return ({ children }: { children: ReactNode }) => (
    <SessionCtx.Provider value={session}>
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    </SessionCtx.Provider>
  );
}

/**
 * Build a `Response` for the fetch mock with our standard envelope shape.
 * Saves boilerplate in every test — most hooks just call `.data` off the
 * envelope and don't care about meta/errors when things go right.
 */
export function envelopeResponse(data: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify({ data, meta: null, errors: null }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
    ...init,
  });
}
