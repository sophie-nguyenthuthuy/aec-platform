"use client";

import { useEffect } from "react";


/**
 * Lazy Sentry SDK initialisation for the browser.
 *
 * Why dynamic-import instead of the recommended `@sentry/nextjs` wrap:
 *
 *   1. The official Next.js Sentry wrapper requires `next.config.mjs`
 *      changes + an `instrumentation.ts` hook + per-route hooks. That's
 *      a heavy lift to install AND it breaks `next dev` for contributors
 *      who haven't run `npm install @sentry/nextjs`.
 *   2. Server-side error capture is handled by the FastAPI Sentry SDK
 *      (see core/observability.py). The vast majority of work happens
 *      in API handlers, not in Next Server Components. Wiring browser-
 *      only Sentry is the 80/20 cut.
 *   3. Dynamic-import means the SDK only loads when (a) the package is
 *      actually installed and (b) NEXT_PUBLIC_SENTRY_DSN is set. Both
 *      conditions usually true in prod, neither in dev → zero JS cost
 *      in dev.
 *
 * To activate: `npm install @sentry/browser` + set
 * `NEXT_PUBLIC_SENTRY_DSN` in the Vercel project. The first deploy
 * with both will start shipping browser errors to Sentry.
 *
 * Until then this component is a hard no-op (no SDK loaded, no
 * network calls, no perf overhead beyond a single useEffect tick).
 */
export function SentryClient() {
  useEffect(() => {
    const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN;
    if (!dsn) return;

    // Use a string variable so static analysis (TS / Next bundler)
    // doesn't fail the build with "Cannot find module '@sentry/browser'"
    // before the package is installed.
    const sentryModule = "@sentry/browser";

    import(/* webpackIgnore: true */ /* @vite-ignore */ sentryModule)
      .then((Sentry: { init: (opts: Record<string, unknown>) => void }) => {
        Sentry.init({
          dsn,
          environment: process.env.NEXT_PUBLIC_AEC_ENV || "production",
          release: process.env.NEXT_PUBLIC_SENTRY_RELEASE,
          // Browser tracing — sample 10% so we capture meaningful perf
          // data without flooding Sentry. Tune via env if needed.
          tracesSampleRate: parseFloat(
            process.env.NEXT_PUBLIC_SENTRY_TRACES_SAMPLE_RATE || "0.1",
          ),
          // Session replay sample rate. 0 = off by default; SOE
          // customers haven't approved screen recording of their UI
          // for vendor analysis. Turn on later if needed.
          replaysSessionSampleRate: 0,
          replaysOnErrorSampleRate: 0,
          // Tag every browser event with `service=web` so the API +
          // worker + web event streams stay grep-able in one project.
          beforeSend(event: { tags?: Record<string, string> }) {
            event.tags = { ...(event.tags || {}), service: "web" };
            return event;
          },
        });
      })
      .catch((err) => {
        // SDK not installed — fail silently. We don't want a `npm
        // install` lapse to spam the JS console in prod.
        if (process.env.NODE_ENV !== "production") {
          console.warn("[sentry] init skipped:", err?.message ?? err);
        }
      });
  }, []);

  return null;
}
