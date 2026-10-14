/** @type {import('next').NextConfig} */
const nextConfig = {
  distDir: process.env.NEXT_DIST_DIR?.trim() || ".next",
  poweredByHeader: false,
  // Dev-only: the local stack is browsed at 127.0.0.1 as well as localhost.
  // Without this Next blocks the /_next/hmr websocket as cross-origin and the
  // dev client never hydrates on the IP origin.
  allowedDevOrigins: ["127.0.0.1"],

  // ---------------------------------------------------------------------------
  // Base path — serve the whole app under a sub-path (e.g. /signal on qiko.ai).
  // Env-driven so the default (empty) keeps root-domain hosting unchanged.
  // ---------------------------------------------------------------------------
  basePath: process.env.NEXT_PUBLIC_BASE_PATH?.trim() || undefined,
  assetPrefix: process.env.NEXT_PUBLIC_ASSET_PREFIX?.trim() || undefined,

  // ---------------------------------------------------------------------------
  // Image optimization — allow remote images from GCS and Google accounts.
  // ---------------------------------------------------------------------------
  images: {
    remotePatterns: [
      {
        protocol: "https",
        hostname: "storage.googleapis.com",
      },
      {
        protocol: "https",
        hostname: "lh3.googleusercontent.com",
      },
      {
        protocol: "https",
        hostname: "*.googleusercontent.com",
      },
      {
        protocol: "https",
        hostname: "**.amazonaws.com",
      },
      {
        protocol: "https",
        hostname: "qiko.ai",
      },
      {
        protocol: "https",
        hostname: "*.qiko.ai",
      },
    ],
  },

  // ---------------------------------------------------------------------------
  // Bundle optimization — tree-shake barrel exports for heavy icon libraries.
  // ---------------------------------------------------------------------------
  experimental: {
    optimizePackageImports: ["lucide-react"],
  },

  // Keep visual stub + fixtures in the serverless trace so MOCK_PREVIEW can
  // answer /api/v1/* on Vercel without a separate backend process.
  outputFileTracingIncludes: {
    "/*": ["./e2e/visual/**/*"],
  },

  // ---------------------------------------------------------------------------
  // The public marketing surface moved to the Website V2 site. These paths are
  // retired here; the edge redirects them as well, and this is the in-app
  // safety net so the old pages can never be served again from this app.
  // ---------------------------------------------------------------------------
  async redirects() {
    const siteUrl = (process.env.NEXT_PUBLIC_QIKO_SITE_URL?.trim() || "https://qiko.ai").replace(
      /\/+$/,
      ""
    );
    // Host-scoped on purpose: qiko.ai/signal/* is split between Website V2 and
    // this app by the Cloudflare worker, so an unconditional redirect to the
    // same URL could loop while a path still routes here. The redirect only
    // fires for requests that reach the app directly on the origin host.
    const marketingRedirects = [
      ["/", `${siteUrl}/signal`],
      ["/guest-audit", `${siteUrl}/signal/guest-audit`],
      ["/sample-report", `${siteUrl}/signal/sample-report`],
      ["/terms", `${siteUrl}/signal/terms`],
      ["/privacy", `${siteUrl}/signal/privacy`],
    ].map(([source, destination]) => ({
      source,
      destination,
      permanent: true,
      has: [{ type: "host", value: "signal-origin.qiko.ai" }],
    }));
    return [
      ...marketingRedirects,
      {
        source: "/dashboard/projects/:projectId/aeo",
        destination: "/dashboard/projects/:projectId/ai-answers",
        permanent: true,
      },
      {
        source: "/dashboard/projects/:projectId/seo",
        destination: "/dashboard/projects/:projectId/google",
        permanent: true,
      },
      {
        source: "/dashboard/projects/:projectId/competitive",
        destination: "/dashboard/projects/:projectId/competitors",
        permanent: true,
      },
      {
        source: "/dashboard/projects/:projectId/recommendations",
        destination: "/dashboard/projects/:projectId/fixes",
        permanent: true,
      },
    ];
  },

  // ---------------------------------------------------------------------------
  // SEC-02: Browser security headers — defense-in-depth baseline.
  // CSP is handled dynamically in middleware.ts (nonce per request).
  // These static headers apply to all routes as a fallback in case the
  // reverse proxy (Caddy) is bypassed or misconfigured.
  // ---------------------------------------------------------------------------
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=()",
          },
          { key: "X-XSS-Protection", value: "0" },
          { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
        ],
      },
      // Cache static marketing pages at the CDN / reverse-proxy layer
      {
        source: "/(about|pricing|faq|docs|contact|terms|privacy)",
        headers: [
          {
            key: "Cache-Control",
            value: "public, s-maxage=3600, stale-while-revalidate=86400",
          },
        ],
      },
      // Long-lived cache for immutable Next.js static assets
      ...(process.env.NODE_ENV === "production"
        ? [
            {
              source: "/_next/static/:path*",
              headers: [
                {
                  key: "Cache-Control",
                  value: "public, max-age=31536000, immutable",
                },
              ],
            },
          ]
        : []),
    ];
  },
};

export default nextConfig;
