import path from "node:path";
import { fileURLToPath } from "node:url";

import createNextIntlPlugin from "next-intl/plugin";

const withNextIntl = createNextIntlPlugin("./i18n/request.ts");

// In a pnpm workspace Next's file tracer walks `../../node_modules` and
// occasionally picks up packages outside the inferred root, leaving
// .next/standalone missing files. Pin the root to the monorepo top so the
// standalone trace is reproducible.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const workspaceRoot = path.resolve(__dirname, "..", "..");

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  transpilePackages: ["@aec/ui", "@aec/types"],
  // typedRoutes requires `.next/types/` from a prior `next build`. CI runs
  // typecheck before build, so the strict `Route<"/...">` literal types
  // aren't generated yet and every literal href becomes a TS error. Re-
  // enable once the CI step order is build → typecheck (slower but accurate)
  // or once Next ships standalone typegen.
  // experimental: { typedRoutes: true },
  // Docker runtime image copies from .next/standalone — requires this.
  // Disabled for local pnpm start (which doesn't support standalone output);
  // re-enable via NEXT_OUTPUT=standalone when building the Docker image.
  ...(process.env.NEXT_OUTPUT === "standalone"
    ? { output: "standalone", outputFileTracingRoot: workspaceRoot }
    : {}),
  // Strict mode now enforced — fix any new violations as they appear.
  typescript: { ignoreBuildErrors: false },
  eslint: { ignoreDuringBuilds: false },
};

export default withNextIntl(nextConfig);
