import type { MetadataRoute } from "next";
import { resolvePublicAppUrl } from "@/lib/public-app-url";

// robots.txt has no async work, so Next prerendered it during the image build,
// where frontend/.env is absent and resolvePublicAppUrl() falls back to
// localhost. That fallback was frozen into the file, and production served
// "Sitemap: http://localhost:3000/sitemap.xml" to every crawler. The env is
// correct at runtime, which is why sitemap.xml, dynamic because it fetches
// content, always had the right URLs.
export const dynamic = "force-dynamic";

export default function robots(): MetadataRoute.Robots {
  const baseUrl = resolvePublicAppUrl();
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        disallow: ["/admin", "/dashboard", "/api"],
      },
    ],
    sitemap: `${baseUrl}/sitemap.xml`,
  };
}
