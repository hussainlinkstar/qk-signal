/**
 * Shared helpers for mapping audit penalties to specific page sections
 * and technical areas, giving users actionable context instead of
 * bare "Missing canonical URL" strings.
 */

/** Map a penalty reason string to a concrete page section / technical area. */
export function mapPenaltySection(reason: string): string {
  const r = reason.toLowerCase();
  if (r.includes("canonical")) return 'HTML Head · <link rel="canonical">';
  if (r.includes("viewport")) return 'HTML Head · <meta name="viewport">';
  if (r.includes("page title") || r.includes("title tag")) return "HTML Head · <title>";
  if (r.includes("meta description")) return 'HTML Head · <meta name="description">';
  if (r.includes("h1")) return "Page Body · Heading Structure";
  if (r.includes("h2")) return "Page Body · Heading Structure";
  if (r.includes("alt text") || r.includes("image alt")) return "Page Body · Image Accessibility";
  if (r.includes("robots")) return 'HTML Head · <meta name="robots">';
  if (r.includes("hreflang")) return "HTML Head · hreflang Tags";
  if (r.includes("open graph") || r.includes("og:")) return "HTML Head · Open Graph Meta";
  if (r.includes("twitter card")) return "HTML Head · Twitter Card Meta";
  if (r.includes("schema") || r.includes("structured data") || r.includes("json-ld"))
    return "Structured Data · JSON-LD";
  if (r.includes("local") && r.includes("schema")) return "Structured Data · LocalBusiness";
  if (r.includes("aeo") && r.includes("schema")) return "Structured Data · FAQ / HowTo / Product";
  if (r.includes("faq")) return "Structured Data · FAQPage Schema";
  if (r.includes("howto")) return "Structured Data · HowTo Schema";
  if (r.includes("product") && r.includes("schema")) return "Structured Data · Product Schema";
  if (r.includes("https")) return "Server · TLS Configuration";
  if (r.includes("http2") || r.includes("http/2")) return "Server · Protocol";
  if (r.includes("ssl") || r.includes("certificate")) return "Server · TLS Configuration";
  if (r.includes("language") || r.includes("lang")) return "HTML Element · lang Attribute";
  if (r.includes("locale")) return "HTML Head · Locale Meta";
  if (
    r.includes("speed") ||
    r.includes("lcp") ||
    r.includes("cls") ||
    r.includes("core web vitals")
  )
    return "Performance · Core Web Vitals";
  return "Technical";
}

/**
 * Map a *deterministic* penalty reason (score_utils.py) to a concrete,
 * actionable fix, the "how", not just a restatement of the "what" already in
 * the reason itself. Used as the recommendation card body for penalties that
 * are not AI-finding-derived; `getDetailedAuditRecommendations` in
 * `reportAdapters.ts` prefers a finding's own `description`/`rationale` when
 * present and only falls back here (or to a generic template if nothing
 * matches) for the ~20 known deterministic score_utils.py penalty reasons.
 */
export function getPenaltyFixGuidance(reason: string): string | null {
  const r = reason.toLowerCase();
  if (r.includes("canonical"))
    return 'Add a <link rel="canonical" href="..."> tag in the page <head> pointing to the preferred URL. This prevents duplicate-content dilution and consolidates ranking signals onto one URL.';
  if (r.includes("viewport"))
    return 'Add <meta name="viewport" content="width=device-width, initial-scale=1"> to the <head>. Without it, mobile browsers render a desktop-width layout, hurting mobile rankings and usability.';
  if (r.includes("noindex"))
    return "Remove the noindex directive (meta robots tag or X-Robots-Tag header) if this page should be indexed. A noindex page is invisible to Google and AI crawlers regardless of any other optimization.";
  if (r.includes("title too short"))
    return "Rewrite the <title> tag to 50-60 characters that include the primary keyword and brand name. Short titles waste valuable SERP real estate and signal weak topical relevance.";
  if (r.includes("missing page title"))
    return "Add a unique, descriptive <title> tag (50-60 characters) to this page. Search engines and AI answer engines use it as the primary label for this content.";
  if (r.includes("meta description too short"))
    return "Expand the meta description to 120-155 characters summarizing the page's value proposition. It directly shapes the SERP snippet and click-through rate.";
  if (r.includes("missing meta description"))
    return "Add a 120-155 character meta description summarizing this page's content. Without one, search engines auto-generate a snippet from body text, which is often less compelling.";
  if (r.includes("multiple h1"))
    return "Keep exactly one <h1> per page and demote the extras to <h2>/<h3>. Multiple H1s dilute the topical signal and confuse heading hierarchy for crawlers and screen readers.";
  if (r.includes("h1 tag"))
    return "Add one <h1> that states the page's main topic in plain language. It is the strongest on-page relevance signal after the title tag.";
  if (r.includes("alt-text") || r.includes("alt text"))
    return "Add descriptive alt text to the images missing it. Alt text drives image-search visibility and is required for accessibility compliance.";
  if (r.includes("thin content"))
    return "Expand this page's body copy with substantive, unique content. Search engines and AI answer engines deprioritize thin pages that don't fully answer the query.";
  if (r.includes("not using https"))
    return "Migrate this page to HTTPS with a valid TLS certificate. HTTP is a confirmed Google ranking penalty and is flagged as insecure by every modern browser.";
  if (r.includes("mixed content"))
    return "Update the HTTP resource references (images, scripts, stylesheets) to HTTPS. Mixed content triggers browser security warnings and can block resources from loading.";
  if (r.includes("aeo-relevant schema"))
    return "Add FAQPage, HowTo, or Article schema matching this page's content type. Structured data is what lets AI answer engines lift a direct answer out of the page.";
  if (r.includes("entity clarity"))
    return "Add Organization (and Person, if applicable) schema.org markup describing the brand's name, URL, logo, and description. This is the baseline signal AI engines use to resolve who this content is about.";
  if (r.includes("vocabulary diversity"))
    return "Vary sentence structure and terminology instead of repeating the same phrases. Low lexical diversity reads as thin or auto-generated content to both readers and AI evaluators.";
  if (r.includes("too complex") || r.includes("fk grade"))
    return "Shorten sentences and simplify word choice to bring the reading grade level down. Content above a 12th-grade reading level is harder for AI engines to extract a clean, quotable answer from.";
  if (r.includes("passive voice"))
    return "Rewrite key sentences in active voice (subject-verb-object). Active voice is easier to parse into a direct answer and reads as more authoritative.";
  if (r.includes("boilerplate"))
    return "Replace generic filler phrases with specific facts, numbers, or examples. Boilerplate language is the single strongest signal of thin, non-authoritative content to AI evaluators.";
  if (r.includes("lcp"))
    return "Optimize the largest visible element (usually a hero image or heading) by compressing images, preloading key assets, and removing render-blocking resources. LCP over 2.5s is flagged by Google as a poor user experience.";
  if (r.includes("cls"))
    return "Reserve explicit width/height (or aspect-ratio) for images, embeds, and ads so they don't shift layout after load. High CLS is a confirmed Core Web Vitals ranking factor.";
  return null;
}
