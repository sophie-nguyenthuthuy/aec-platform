FROM node:20-alpine AS deps
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/package.json
COPY packages/ui/package.json packages/ui/package.json
COPY packages/types/package.json packages/types/package.json
RUN pnpm install --frozen-lockfile || pnpm install

FROM node:20-alpine AS builder
WORKDIR /app
RUN corepack enable
COPY --from=deps /app /app
COPY . .

# `NEXT_PUBLIC_*` env vars are inlined into the client JS bundle at
# `next build` time (the very point of the prefix). Without them, the
# bundle ships with `undefined` literals and `supabaseBrowser()` /
# `lib/supabase-env.ts::readSupabaseEnv()` throw on the first user
# interaction in production. Take them in as build args so the deploy
# workflow can wire them from secrets (see .github/workflows/deploy.yml
# `## Secrets`).
#
# Default values are intentional: empty strings (not unset) so the
# `if (!url || !publishableKey)` check inside `readSupabaseEnv` short-
# circuits to a clear runtime error message. Unset would still throw
# but with a confusing "process.env.X is undefined" instead.
ARG NEXT_PUBLIC_API_BASE=""
ARG NEXT_PUBLIC_SUPABASE_URL=""
ARG NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=""
ENV NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE \
    NEXT_PUBLIC_SUPABASE_URL=$NEXT_PUBLIC_SUPABASE_URL \
    NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=$NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY

RUN pnpm --filter @aec/web build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/apps/web/.next/standalone ./
COPY --from=builder /app/apps/web/.next/static ./apps/web/.next/static
COPY --from=builder /app/apps/web/public ./apps/web/public
EXPOSE 3000
CMD ["node", "apps/web/server.js"]
