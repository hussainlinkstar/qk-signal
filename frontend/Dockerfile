# Stage 1: Install dependencies
FROM node:24-alpine AS deps
WORKDIR /app

# Copy package.json and package-lock.json to leverage Docker cache
COPY package.json package-lock.json* ./

# Install dependencies
RUN npm install

# Stage 2: Build the application
FROM node:24-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Prevent OOM: raise heap limit and skip Next.js telemetry to reduce peak memory.
ENV NODE_OPTIONS="--max-old-space-size=3072"
ENV NEXT_TELEMETRY_DISABLED=1

# Base path (e.g. /signal) must be present at build time so Next.js bakes
# basePath/assetPrefix and inlines NEXT_PUBLIC_BASE_PATH into the client bundle.
ARG NEXT_PUBLIC_BASE_PATH=""
ARG NEXT_PUBLIC_ASSET_PREFIX=""
ENV NEXT_PUBLIC_BASE_PATH=$NEXT_PUBLIC_BASE_PATH
ENV NEXT_PUBLIC_ASSET_PREFIX=$NEXT_PUBLIC_ASSET_PREFIX

# Everything else prefixed NEXT_PUBLIC_ is inlined by Next at build time too,
# not read at runtime, so a value that only exists in the server .env never
# reaches the browser. Only the two above were passed, which is why production
# shipped with no tag manager, no GA4, no browser error reporting and no search
# console verification, while all of them sat configured on the host.
ARG NEXT_PUBLIC_APP_URL=""
ARG NEXT_PUBLIC_API_BASE_URL=""
ARG NEXT_PUBLIC_BACKEND_PUBLIC_URL=""
ARG NEXT_PUBLIC_GTM_ID=""
ARG NEXT_PUBLIC_GA4_MEASUREMENT_ID=""
ARG NEXT_PUBLIC_GOOGLE_SITE_VERIFICATION=""
ARG NEXT_PUBLIC_BING_SITE_VERIFICATION=""
ARG NEXT_PUBLIC_SENTRY_DSN=""
ARG NEXT_PUBLIC_SENTRY_ENABLED=""
ARG NEXT_PUBLIC_SENTRY_ENVIRONMENT=""
ARG NEXT_PUBLIC_SENTRY_RELEASE=""
ARG NEXT_PUBLIC_SENTRY_TRACES_SAMPLE_RATE=""
ARG NEXT_PUBLIC_SENTRY_REPLAYS_SESSION_SAMPLE_RATE=""
ARG NEXT_PUBLIC_SENTRY_REPLAYS_ON_ERROR_SAMPLE_RATE=""
ARG NEXT_PUBLIC_SUPPORT_EMAIL=""
ARG NEXT_PUBLIC_CONTACT_EMAIL=""
ARG NEXT_PUBLIC_BILLING_EMAIL=""
ARG NEXT_PUBLIC_PRIVACY_EMAIL=""
ARG NEXT_PUBLIC_CONTACT_WEBMAIL_PROVIDER=""
# Base URL of the shared Qiko marketing site (qiko-website-v2), for cross-linking Home/Labs from
# Signal's own marketing header/footer. Defaults to https://qiko.ai in code if unset (see
# lib/qiko-site-url.ts). SIGNAL-1009.
ARG NEXT_PUBLIC_QIKO_SITE_URL=""
# Master switch for the Arabic/RTL foundation (lib/i18nFlags.ts). On by default;
# only the literal "false" turns it off, so an empty arg still enables Arabic.
# Kept as a build arg like every other NEXT_PUBLIC_* because it is inlined at
# build time; "false" needs a rebuild, not a restart. SIGV2-1060.
ARG NEXT_PUBLIC_ENABLE_RTL=""
ENV NEXT_PUBLIC_APP_URL=$NEXT_PUBLIC_APP_URL
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
ENV NEXT_PUBLIC_BACKEND_PUBLIC_URL=$NEXT_PUBLIC_BACKEND_PUBLIC_URL
ENV NEXT_PUBLIC_GTM_ID=$NEXT_PUBLIC_GTM_ID
ENV NEXT_PUBLIC_GA4_MEASUREMENT_ID=$NEXT_PUBLIC_GA4_MEASUREMENT_ID
ENV NEXT_PUBLIC_GOOGLE_SITE_VERIFICATION=$NEXT_PUBLIC_GOOGLE_SITE_VERIFICATION
ENV NEXT_PUBLIC_BING_SITE_VERIFICATION=$NEXT_PUBLIC_BING_SITE_VERIFICATION
ENV NEXT_PUBLIC_SENTRY_DSN=$NEXT_PUBLIC_SENTRY_DSN
ENV NEXT_PUBLIC_SENTRY_ENABLED=$NEXT_PUBLIC_SENTRY_ENABLED
ENV NEXT_PUBLIC_SENTRY_ENVIRONMENT=$NEXT_PUBLIC_SENTRY_ENVIRONMENT
ENV NEXT_PUBLIC_SENTRY_RELEASE=$NEXT_PUBLIC_SENTRY_RELEASE
ENV NEXT_PUBLIC_SENTRY_TRACES_SAMPLE_RATE=$NEXT_PUBLIC_SENTRY_TRACES_SAMPLE_RATE
ENV NEXT_PUBLIC_SENTRY_REPLAYS_SESSION_SAMPLE_RATE=$NEXT_PUBLIC_SENTRY_REPLAYS_SESSION_SAMPLE_RATE
ENV NEXT_PUBLIC_SENTRY_REPLAYS_ON_ERROR_SAMPLE_RATE=$NEXT_PUBLIC_SENTRY_REPLAYS_ON_ERROR_SAMPLE_RATE
ENV NEXT_PUBLIC_SUPPORT_EMAIL=$NEXT_PUBLIC_SUPPORT_EMAIL
ENV NEXT_PUBLIC_CONTACT_EMAIL=$NEXT_PUBLIC_CONTACT_EMAIL
ENV NEXT_PUBLIC_BILLING_EMAIL=$NEXT_PUBLIC_BILLING_EMAIL
ENV NEXT_PUBLIC_PRIVACY_EMAIL=$NEXT_PUBLIC_PRIVACY_EMAIL
ENV NEXT_PUBLIC_CONTACT_WEBMAIL_PROVIDER=$NEXT_PUBLIC_CONTACT_WEBMAIL_PROVIDER
ENV NEXT_PUBLIC_QIKO_SITE_URL=$NEXT_PUBLIC_QIKO_SITE_URL
ENV NEXT_PUBLIC_ENABLE_RTL=$NEXT_PUBLIC_ENABLE_RTL

# Build the Next.js application for production
RUN npm run build

# Stage 3: Production image - a smaller, optimized image
FROM node:24-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production

RUN addgroup --system --gid 1001 nodejs && adduser --system --uid 1001 nextjs

# Copy only the necessary artifacts from the builder stage
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next-build ./.next-build
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/next.config.mjs ./next.config.mjs

USER nextjs

# Expose the port Next.js runs on
EXPOSE 3000

# DL3025 (JSON notation for CMD) is waived for the HEALTHCHECK only: the
# `|| exit 1` fallback cannot be expressed in exec form, and rewriting the
# probe would change how an unhealthy frontend is reported to compose and to
# Caddy. hadolint 2.12.0 (the version pinned by hadolint-action v3.1.0) does
# not flag this; newer hadolint does, so the pragma is here to keep the step
# green across an action bump.
# hadolint ignore=DL3025
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://localhost:3000/ || exit 1

# The default command to start the app
CMD ["npm", "start"]
