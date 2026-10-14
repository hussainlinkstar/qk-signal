import type { MetadataRoute } from "next";

/* The marketing pages this sitemap listed were retired in WEB-1008; the
   canonical copies live on qiko-website-v2, which owns the marketing
   sitemap for the Signal pages. No crawlable app routes remain here. */
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  return [];
}
