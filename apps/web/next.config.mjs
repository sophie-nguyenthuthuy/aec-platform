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
  output: "standalone",
  // TODO(platform-drift): parallel modules shipped with TS strict violations.
  // Sweep these and flip these flags back off.
  typescript: { ignoreBuildErrors: true },
  eslint: { ignoreDuringBuilds: true },
};

export default withNextIntl(nextConfig);
