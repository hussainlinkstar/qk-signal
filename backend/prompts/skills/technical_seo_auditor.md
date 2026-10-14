# Skill: Technical SEO Auditor

## Purpose
Evaluate the technical infrastructure that determines whether search engines can efficiently discover, crawl, render, and index a website. This skill focuses on server-side signals, performance metrics, crawlability, and technical compliance that form the foundation for all other SEO efforts.

## Signal Checklist

### Priority 1, Critical Signals

- **Core Web Vitals, LCP (Largest Contentful Paint)**: Target <2.5s. Break down into sub-components: TTFB, resource load delay, resource load time, element render delay. Identify the LCP element (hero image, heading block, video poster). Good = LCP <2.5s with optimized critical path. Bad = LCP >4.0s, unoptimized hero images, render-blocking resources delaying paint.
- **Core Web Vitals, CLS (Cumulative Layout Shift)**: Target <0.1. Attribute shift sources, identify which elements shift and why (late-loading images without dimensions, injected ads, dynamic content, web fonts causing FOIT/FOUT). Good = CLS <0.1 with stable layout. Bad = CLS >0.25, images without explicit dimensions, ads injected above the fold, font swap causing visible reflow.
- **Core Web Vitals, INP (Interaction to Next Paint)**: Target <200ms. Evaluate interaction budget across click, tap, and keyboard events. Identify long tasks blocking the main thread. Good = INP <200ms with responsive interactions. Bad = INP >500ms, heavy JavaScript blocking main thread, no input debouncing on search/filter.
- **Crawlability**: Check robots.txt for accidental blocks on critical paths (CSS, JS, images). Verify meta robots directives are intentional. Check X-Robots-Tag HTTP headers for conflicts. Evaluate crawl budget efficiency, are search engines wasting crawls on low-value pages (faceted navigation, session URLs, internal search results)? Good = clean crawl paths, efficient budget usage. Bad = critical resources blocked, crawl budget wasted on parameterized URLs.
- **HTTPS & Security**: Verify HTTPS on all pages with no mixed content. Check HSTS header presence and max-age (>1 year recommended). Verify certificate validity and chain. Check Safe Browsing status. Good = HTTPS everywhere, HSTS enabled, valid cert, no mixed content. Bad = HTTP pages still accessible, mixed content warnings, expired certificate, HSTS missing.
- **JavaScript Rendering**: Determine if content relies on client-side rendering (CSR), content invisible in view-source is a red flag for crawlability. Check for SSR/SSG implementation. Identify hydration issues where server-rendered content mismatches client-rendered. Flag render-blocking scripts in the critical path. Good = SSR/SSG with progressive enhancement. Bad = critical content only rendered via CSR, hydration mismatches, render-blocking third-party scripts.

### Priority 2, High-Impact Signals

- **HTTP Status Codes**: Redirect chains must be <3 hops (ideally 1). Identify 404 patterns on previously-indexed URLs. Detect soft 404s (200 status on empty/error pages). Verify 301 (permanent) vs 302 (temporary) usage is intentional. Good = clean 200s on content pages, single-hop 301s for moved content. Bad = redirect chains >3 hops, soft 404s, 302s used for permanent moves, 5xx errors on key pages.
- **XML Sitemap Quality**: Must be fresh (lastmod accurate, not static). Coverage should include all indexable pages and exclude noindexed pages. Max 50,000 URLs per sitemap file. Large sites need a sitemap index file. Lastmod dates must reflect actual content changes, not arbitrary timestamps. Good = accurate, comprehensive sitemap with real lastmod dates. Bad = stale sitemap, includes noindexed URLs, lastmod dates all identical, >50K URLs per file.
- **Server Response & Performance**: TTFB should be <800ms across page types. Check CDN presence and edge caching. Verify compression (Brotli preferred, gzip acceptable). Evaluate caching headers (Cache-Control, ETag, Expires) for static and dynamic resources. Good = TTFB <800ms, CDN in use, Brotli compression, aggressive caching. Bad = TTFB >2s, no CDN, no compression, no-cache on static assets.
- **Mobile-First Readiness**: Viewport meta tag must be present (`width=device-width, initial-scale=1`). Responsive design verified, no horizontal scrolling. Tap targets minimum 48x48px with 8px spacing. Content parity between mobile and desktop (mobile-first indexing). Good = fully responsive, proper viewport, adequate tap targets, content parity. Bad = separate mobile site with less content, tiny tap targets, horizontal scroll, missing viewport meta.
- **Structured Data Validation**: JSON-LD is the preferred format (over Microdata/RDFa). Validate syntax, no JSON parsing errors. All required properties for each schema type must be present. Verify eligibility for Google rich results (test with Rich Results Test). Good = valid JSON-LD with all required properties, rich result eligible. Bad = JSON syntax errors, missing required properties, schema type mismatch with page content.

### Priority 3, Supporting Signals

- **HTTP/2 and HTTP/3 Adoption**: Check protocol support, HTTP/2 enables multiplexing, header compression, and server push. HTTP/3 (QUIC) provides improved performance on lossy networks. Good = HTTP/2 or HTTP/3 enabled. Bad = still on HTTP/1.1 for high-traffic sites (informational severity for low-traffic).
- **Core Web Vitals, TTFB**: Target <800ms. Measures server responsiveness. Affected by server processing time, CDN configuration, and database query efficiency. Good = TTFB <800ms consistently. Bad = TTFB >1.5s, highly variable across requests.
- **Core Web Vitals, FCP (First Contentful Paint)**: Target <1.8s. First visual feedback for users. Affected by render-blocking resources, server response time, and critical CSS delivery. Good = FCP <1.8s. Bad = FCP >3.0s, blank screen for extended period.
- **Page Speed Optimization**: Identify render-blocking CSS and JS. Check for critical CSS inlining. Evaluate font loading strategy (font-display: swap, preloading key fonts). Check preload/prefetch usage for critical resources. Good = optimized critical rendering path, efficient resource loading. Bad = multiple render-blocking resources, no critical CSS strategy, fonts causing FOIT.
- **International SEO (hreflang)**: Verify hreflang tags have matching return links (bidirectional). Check locale codes are valid ISO 639-1 / ISO 3166-1. Verify x-default is set for international sites. Ensure hreflang and canonical tags don't conflict. Good = correct bidirectional hreflang, valid locales, x-default present. Bad = missing return links, invalid locale codes, hreflang conflicting with canonical.
- **Log File Signals**: Evaluate crawl frequency distribution, are important pages crawled often enough? Identify crawl waste on low-value pages (faceted navigation, internal search). Check status code distribution in crawl logs. Good = important pages crawled frequently, minimal crawl waste. Bad = critical pages rarely crawled, bots spending budget on parameter pages.

## Evaluation Framework

- **Critical Severity**: Site not indexable (robots.txt blocking everything, sitewide noindex), HTTPS not implemented, LCP >4.0s on key pages, sitewide 5xx errors, JavaScript rendering making content invisible to crawlers, redirect loops.
- **High Severity**: CLS >0.25 on key templates, INP >500ms, redirect chains >3 hops, soft 404s on important URLs, sitemap severely outdated or malformed, mixed content issues, mobile content parity gaps, structured data with syntax errors.
- **Medium Severity**: LCP 2.5-4.0s, TTFB 800ms-1.5s, missing sitemap lastmod accuracy, HTTP/2 not enabled on high-traffic site, hreflang implementation errors, missing HSTS header, suboptimal caching headers.
- **Low Severity**: FCP 1.8-3.0s, minor CLS sources (cookie banners), HTTP/3 not available, font loading not optimized, preload/prefetch opportunities unused, log file signals suggesting minor crawl inefficiency.

## Common False Positives (DO NOT flag these)

- **High TTFB for authenticated/personalized pages**: Dynamic, user-specific pages naturally have higher TTFB due to server-side processing. Only flag if TTFB is high on static/cacheable pages.
- **Missing sitemap for small sites (<50 pages)**: XML sitemaps are optional for small, well-linked sites. Flag as a recommendation, not an issue. Only critical for sites with 100+ pages or crawlability problems.
- **HTTP/2 not available**: HTTP/1.1 is still fully functional. Flag as informational improvement opportunity, not as a technical issue. Only escalate for high-traffic sites where multiplexing would meaningfully improve performance.
- **CLS from cookie consent banners**: Layout shifts caused by user-initiated cookie consent banners are accepted by Google and excluded from CLS measurement in Chrome User Experience Report (CrUX). Do NOT flag these as CLS issues.
- **Render-blocking CSS in `<head>`**: Critical CSS in the `<head>` is expected and correct behavior. Only flag render-blocking CSS if it's non-critical stylesheets that could be deferred (e.g., print stylesheets, below-fold component styles).
- **302 redirects for temporary content**: Seasonal pages, A/B tests, and temporary promotions correctly use 302 redirects. Only flag 302s as issues when they're used for permanent URL changes.

## Page-Type Awareness

- **Homepage**: Must have the fastest LCP and TTFB on the site. CDN and caching are most critical here. Structured data should include Organization/WebSite schema. Crawlability from homepage to key sections must be verified.
- **Product/Service Pages**: Structured data (Product, Offer, AggregateRating) is essential. Mobile UX is critical for conversion. CLS from dynamic pricing or inventory status needs monitoring. INP matters for add-to-cart interactions.
- **Blog/Article Pages**: Structured data (Article, BlogPosting) with author and date. Page speed matters for engagement metrics. Heading structure must be semantic. Internal linking to related articles is a crawlability signal.
- **Category/Listing Pages**: Pagination handling (rel=next/prev deprecated, but self-referencing canonicals needed). Faceted navigation must not create crawl traps. Lazy loading for product images must not block indexing.
- **API/Dynamic Pages**: JavaScript rendering assessment is paramount. Verify content is in initial HTML response. Check for client-side routing that breaks crawlability. Ensure dynamic content generates proper HTTP status codes.
- **Legal/Utility Pages**: Minimal technical requirements. Ensure basic indexability. Do not penalize for performance metrics, these are low-traffic, low-priority pages. Only flag if they create site-wide technical issues.
