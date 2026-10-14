# SEO Industry Standards & Best Practices (2026)

## 1. Core Web Vitals (CWV) 2026
- **Largest Contentful Paint (LCP)**: Must be ≤ 2.5 s (good), > 4.0 s (poor). Sub-components to audit: server response time (TTFB), resource load delay (render-blocking CSS/JS), resource load duration, and element render delay. LCP element should be in the initial viewport and not lazy-loaded.
- **Cumulative Layout Shift (CLS)**: Must be ≤ 0.1 (good), > 0.25 (poor). Use Layout Instability API attribution to identify shift sources: images/iframes without dimensions, dynamically injected content, web fonts causing FOIT/FOUT, and late-loading ads.
- **Interaction to Next Paint (INP)**: Must be ≤ 200 ms (good), > 500 ms (poor). Audit main-thread blocking time, long tasks (> 50 ms), heavy event handlers, forced synchronous layouts, and excessive DOM size (target < 1,500 nodes). Break long tasks via `scheduler.yield()` or `requestIdleCallback`.
- **First Contentful Paint (FCP)**: Should be ≤ 1.8 s. Impacted by render-blocking resources, server response time, and large DOM trees.
- **Time to First Byte (TTFB)**: Should be ≤ 800 ms. Audit server processing, CDN configuration, and redirect chains (maximum 2 redirects).

## 2. E-E-A-T Deep Framework
- **Experience**: Content must show first-hand evidence, original photos, personal anecdotes, proprietary data, case studies, or user-generated reviews. Flag content that lacks any experiential markers.
- **Expertise**: Author entity must be identifiable. Check for: author bio with credentials, author schema markup (`Person` type), topical depth (covers subtopics comprehensively, not superficially), and links to author's body of work or professional profiles.
- **Authoritativeness**: Site-level authority assessed by: topical authority (depth and breadth of coverage within a niche), inbound links from peer/authoritative domains, brand mentions across the web, and recognized affiliations or awards. Page should demonstrate it is the best answer for the query.
- **Trustworthiness**: Require HTTPS/SSL, visible privacy policy, terms of service, accessible contact information (physical address or phone for YMYL), transparent editorial policy, clear ad/affiliate disclaimers, visible review signals (ratings, testimonials), and accurate "last updated" dates.

## 3. Semantic HTML & Page Architecture
- **Heading Hierarchy**: Exactly one `<h1>` per page matching the page topic. Sequential `<h2>`-`<h6>` with no skipped levels. Headings must be descriptive (not generic like "Read More").
- **Semantic Tags**: Use `<main>` (one per page), `<article>`, `<section>`, `<nav>`, `<aside>`, `<header>`, `<footer>` appropriately. Avoid `<div>` soup, content-bearing blocks must use semantic elements.
- **Landmark Roles**: Implicit ARIA landmarks from semantic elements should be present: `banner`, `navigation`, `main`, `contentinfo`. Add explicit `role` attributes only when semantic HTML cannot be used.
- **Content-to-Code Ratio**: Visible text content should represent ≥ 25 % of total HTML size. Pages with < 10 % ratio are flagged as code-heavy/thin.
- **HTML5 Sectioning Model**: Each `<section>` and `<article>` should have its own heading. Avoid nested `<main>` elements. Use `<figure>` and `<figcaption>` for illustrative media.

## 4. On-Page Signal Standards
- **Title Tag**: 50-60 characters, primary keyword within the first 30 characters. Unique per page. No keyword stuffing. Include brand name at the end separated by ` | ` or `, `.
- **Meta Description**: 150-160 characters, include primary keyword, contain a clear CTA or value proposition. Unique per page. Must not duplicate the title tag.
- **Canonical Tag**: Every indexable page must have a self-referencing `<link rel="canonical">`. Cross-domain canonicals must return 200. No canonical pointing to a redirected URL.
- **Open Graph / Twitter Card**: Require `og:title`, `og:description`, `og:image` (1200×630 px min), `og:url`, `og:type`. Twitter Card: `twitter:card`, `twitter:title`, `twitter:description`, `twitter:image`.
- **Hreflang**: Required for multi-language/multi-region sites. Must include self-referencing hreflang. Every hreflang must have a reciprocal return tag. Include `x-default` for fallback.
- **Robots Meta**: Use `index, follow` as default. Apply `noindex` only to utility pages (login, thank-you, internal search results). Never `noindex` pages linked in the sitemap.

## 5. Content Quality Standards
- **Search Intent Alignment**: Map every page to a single intent type, Informational, Navigational, Commercial Investigation, or Transactional. Content format must match intent (e.g., listicles for comparison intent, product pages for transactional).
- **Topical Depth**: Content must cover primary topic and semantically related subtopics. Flag thin content (< 300 words for articles, < 150 words for product pages) unless the format justifies brevity. Assess entity coverage and comprehensiveness relative to top-ranking competitors.
- **Content Freshness**: Publish dates and "last updated" dates must be present and accurate. YMYL content must be reviewed/updated at minimum annually. Stale evergreen content (> 18 months without update) should be flagged.
- **Readability**: Target Flesch-Kincaid grade level ≤ 9 for general audiences. Short paragraphs (≤ 4 sentences), bulleted/numbered lists for scanability, and clear subheadings every 200-300 words.
- **Multimedia Integration**: Articles should include at least one relevant image or video. All media must have descriptive alt text or transcripts. Avoid walls of unbroken text.
- **Duplicate / Thin Content**: Flag pages with > 70 % content similarity to other pages on the same domain. Consolidate or canonicalize duplicate pages. Identify boilerplate-heavy pages where unique content is < 30 % of page text.

## 6. Internal Linking Architecture
- **Hub-and-Spoke Topology**: Pillar (hub) pages must link to all related cluster (spoke) pages. Every spoke page must link back to its hub. Cross-link related spokes where contextually relevant.
- **Orphan Page Detection**: Every indexable page must have at least one internal link pointing to it. Pages discoverable only via sitemap (no internal links) are flagged as orphans.
- **Anchor Text Descriptiveness**: Anchor text must be descriptive of the target page content. Flag generic anchors ("click here", "read more", "learn more"). Avoid exact-match keyword anchor over-optimization (> 30 % of internal anchors using the same phrase).
- **Click Depth**: All key landing pages must be reachable within 3 clicks from the homepage. Deep pages (4+ clicks) receive reduced crawl priority and should be restructured.
- **Breadcrumb Implementation**: Breadcrumbs required on all pages except the homepage. Must use `BreadcrumbList` structured data. Breadcrumb path must reflect site hierarchy accurately.

## 7. Technical Crawlability
- **robots.txt**: Must exist at domain root, return 200, and not block critical resources (CSS, JS, images needed for rendering). Validate with Google's robots.txt tester. Disallow utility/duplicate paths only.
- **XML Sitemap**: Must exist, be referenced in robots.txt, return 200, contain only canonical indexable URLs (200 status, not noindexed). Max 50,000 URLs or 50 MB uncompressed per file. Use sitemap index for larger sites. `<lastmod>` dates must reflect actual content changes.
- **Crawl Budget Optimization**: Minimize redirect chains (max 2 hops), eliminate soft 404s, reduce parameter-based duplicate URLs. Ensure server response times < 500 ms for Googlebot.
- **JavaScript Rendering**: Critical content must be present in initial HTML or server-side rendered. Client-side-only rendered content risks delayed or missed indexing. Test with "View Page Source" vs rendered DOM, key content must appear in source.
- **Parameter Handling**: Use `rel="canonical"` to consolidate parameterized URLs, and keep sort/filter variations out of the index with canonicals and `robots.txt`. The Search Console URL Parameters tool was retired in 2022; do not recommend declaring parameters there.
- **Faceted Navigation**: Filter/facet combinations must not create exponential crawlable URLs. Use `noindex` or canonical tags on low-value facet combinations. Limit indexable facet pages to those with genuine search demand.
- **Pagination**: Use self-referencing canonicals on each paginated page. Implement `<a href>` links between pages (not JS-only pagination). Consider "load more" or infinite scroll with progressive enhancement.

## 8. Image & Media Optimization
- **Next-Gen Formats**: Serve images in WebP or AVIF with JPEG/PNG fallback via `<picture>` element or server-side content negotiation. Flag any images served only as PNG/JPEG when lossy compression is acceptable.
- **Responsive Images**: Use `srcset` and `sizes` attributes to serve appropriately sized images per viewport. Never serve desktop-resolution images to mobile devices.
- **Lazy Loading**: Apply `loading="lazy"` to below-the-fold images. Never lazy-load the LCP image or above-the-fold hero images. Use `fetchpriority="high"` on the LCP image.
- **Explicit Dimensions**: All `<img>` and `<video>` elements must have `width` and `height` attributes (or equivalent CSS aspect-ratio) to prevent CLS.
- **Descriptive Filenames**: Image filenames should be descriptive and hyphen-separated (e.g., `blue-running-shoes-side-view.webp`), not auto-generated hashes.
- **Alt Text**: Every meaningful `<img>` must have descriptive, concise alt text (≤ 125 characters). Decorative images use `alt=""`. Avoid keyword stuffing in alt attributes.
- **Video Structured Data**: Videos must have `VideoObject` schema with `name`, `description`, `thumbnailUrl`, `uploadDate`, and `contentUrl` or `embedUrl`.

## 9. Mobile-First Standards
- **Viewport Meta**: Require `<meta name="viewport" content="width=device-width, initial-scale=1">`. No `maximum-scale=1` or `user-scalable=no` (accessibility violation).
- **Responsive Design**: Layout must adapt fluidly to viewports from 320 px to 2560 px wide. No horizontal scrolling at any breakpoint.
- **Tap Target Spacing**: Interactive elements must be ≥ 48 × 48 CSS pixels with ≥ 8 px spacing between adjacent targets. Flag clustered links and buttons.
- **Mobile Content Parity**: All content, structured data, and metadata present on desktop must also be present on mobile. Hidden content behind toggles/accordions is indexable but should expand by default on mobile if it is primary content.

## 10. Security & Trust Signals
- **HTTPS Everywhere**: All pages, resources (images, scripts, stylesheets), and internal links must use HTTPS. No mixed content. HTTP URLs must 301-redirect to HTTPS.
- **HSTS**: Serve `Strict-Transport-Security` header with `max-age` ≥ 31536000 (1 year) and `includeSubDomains`. Preload list inclusion recommended.
- **Mixed Content Elimination**: Zero tolerance for HTTP resources loaded on HTTPS pages. Audit all embedded media, iframes, scripts, and stylesheets.
- **Safe Browsing**: Site must not appear on Google Safe Browsing, PhishTank, or any malware blocklists. Flag any deceptive download buttons or intrusive interstitials.

## 11. International SEO
- **Hreflang Implementation**: Use `<link rel="alternate" hreflang="x">` in `<head>`, HTTP headers (for PDFs), or XML sitemap. Every hreflang annotation must be reciprocated by the target page. Include `x-default` for language/region selector or fallback page.
- **Locale Targeting**: Use ISO 639-1 language codes and optional ISO 3166-1 Alpha-2 region codes (e.g., `en-US`, `fr-CA`). Do not use unsupported codes.
- **Content Parity Across Languages**: Translated pages must not be machine-translated without human review. Each locale must have equivalent content depth, do not serve stub/partial translations.
- **URL Structure**: Prefer subdirectories (`/en/`, `/fr/`) for most cases. Use ccTLDs (`.de`, `.fr`) only when strong geo-targeting is required. Subdomains (`en.example.com`) are acceptable but consolidate less link equity.

## 12. AI Crawler Accessibility
- **AI Bot Directives**: Define explicit `robots.txt` rules for AI crawlers. Either allow or block per business policy, but the directive must be intentional, not absent. Training and search are separate opt-outs and must be advised on separately, because blocking the wrong one removes the site from AI answers rather than from training data:
  - Search, decides whether the site can be cited: `OAI-SearchBot` (ChatGPT), `Claude-SearchBot`, `PerplexityBot`. Blocking these removes the site from those answers.
  - Training: `GPTBot` (OpenAI), `ClaudeBot` (Anthropic), `Google-Extended` (Gemini and AI Overviews training), `CCBot`, `Bytespider`, `Applebot-Extended`. Blocking these does not affect search rankings or AI-answer eligibility.
  - User-initiated fetches: `ChatGPT-User`, `Claude-User`. Triggered by a person asking a question, so `robots.txt` may not apply.
  - `Googlebot` is ordinary search indexing, not an AI crawler. Never advise blocking it as an AI measure. `anthropic-ai` and `Claude-Web` are retired names kept only for reading old logs.
- **Content Without JavaScript**: Key page content must be accessible without JavaScript execution. AI crawlers and extractors may not render JS. Ensure SSR or static HTML fallback for all indexable content.
- **Structured Data for AI Extraction**: Use JSON-LD structured data (`Article`, `Product`, `LocalBusiness`, `Organization`, `BreadcrumbList`) to provide machine-readable content summaries. This improves AI model comprehension and citation accuracy. `FAQPage` and `HowTo` no longer produce rich results and must not be recommended.
- **Quotable Content Blocks**: Ensure pages contain clear, self-contained passages (definitions, summaries, how-to steps) that AI models can extract and attribute. Use descriptive headings to segment content into citable units.
