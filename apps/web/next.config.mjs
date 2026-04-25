import createNextIntlPlugin from "next-intl/plugin";

const withNextIntl = createNextIntlPlugin("./i18n/request.ts");

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  transpilePackages: ["@aec/ui", "@aec/types"],
  experimental: {
    typedRoutes: true,
  },
  // Docker runtime image copies from .next/standalone — requires this.
  // Disabled for local pnpm start (which doesn't support standalone output);
  // re-enable via NEXT_OUTPUT=standalone when building the Docker image.
  ...(process.env.NEXT_OUTPUT === "standalone" ? { output: "standalone" } : {}),
  // Strict mode now enforced — fix any new violations as they appear.
  typescript: { ignoreBuildErrors: false },
  eslint: { ignoreDuringBuilds: false },
};

export default withNextIntl(nextConfig);
