# Skill: AI Crawler Readiness

## Purpose
Evaluate how well a website's content and technical infrastructure support discovery, extraction, and citation by AI systems including large language models, retrieval-augmented generation pipelines, and AI-powered search engines. This skill identifies barriers that prevent AI systems from accessing, understanding, and accurately representing a site's content.

## Signal Checklist

### Priority 1, Critical Signals

- **Content Without JavaScript**: Verify that key content (headings, body text, structured data, navigation) is accessible in the raw HTML response without JavaScript execution. AI crawlers, including GPTBot, CCBot, and most RAG indexers, rarely execute JavaScript. Test by viewing page source or using `curl` to fetch the URL. Good = full content visible in the initial HTML response, text nodes present without script execution. Bad = content loaded entirely via client-side JS frameworks (React SPA, Vue SPA) with empty initial HTML shells, critical text injected by XHR/fetch calls after page load.

- **SSR/Static HTML Verification**: Confirm the server delivers pre-rendered HTML containing all primary content. Check the initial server response (not the browser-rendered DOM) for complete content. Good = complete DOM with headings, body text, and structured data in the initial server response; frameworks using SSR (Next.js SSR/SSG, Nuxt, Astro) that deliver pre-rendered HTML. Bad = blank `<div id="root"></div>` or `<div id="app"></div>` requiring client-side hydration, content injected by JavaScript after page load, loading spinners visible in raw HTML.

- **Clean HTML Structure**: Assess semantic markup quality, proper use of `<article>`, `<section>`, `<nav>`, `<header>`, `<main>`, `<aside>`, and correct `<h1>`-`<h6>` heading hierarchy. AI extraction pipelines rely on semantic landmarks to identify content boundaries and hierarchy. Good = logical nesting with minimal depth (<=6 levels), semantic tags wrapping content regions, single `<main>` element containing primary content, headings in sequential order. Bad = deeply nested div-soup (>8 levels of meaningless divs), content inside iframes or shadow DOM, tables used for layout, no semantic landmarks, heading levels skipped (h1 → h4).

- **RAG Chunk Quality**: Evaluate whether content sections are self-contained and extractable, each heading-to-content block should make sense in isolation when extracted by a RAG system. Headings should clearly describe the section's topic, and content should answer the implicit question posed by the heading. Good = descriptive headings followed by focused, complete paragraphs that answer an implicit question; each section works as a standalone knowledge chunk; consistent heading-to-content pattern throughout the page. Bad = sections that depend on surrounding context to make sense ("As mentioned above..."), vague headings like "More Info", "Details", or "Overview"; content that requires reading the full page to understand any single section.

- **AI Bot Directives**: Check robots.txt for explicit rules addressing known AI crawlers. Search crawlers that decide citations: OAI-SearchBot, Claude-SearchBot, PerplexityBot. Training crawlers: GPTBot, ClaudeBot, Google-Extended, CCBot, Bytespider, Applebot-Extended. User-initiated: ChatGPT-User, Claude-User. `Googlebot` is ordinary search indexing and must never be treated as an AI crawler. Assess whether rules are intentional and documented vs. accidentally blocking or inadvertently permitting. Good = intentional, documented decisions (explicit allow or disallow per bot with clear reasoning), separate user-agent blocks for AI-specific crawlers. Bad = no awareness of AI crawlers while restricting general crawl access via broad rules, accidental blocking via overly broad `Disallow: /` patterns, wildcard rules that inadvertently catch AI bots.

### Priority 2, High-Impact Signals

- **Citation-Friendly Content**: Check for quotable standalone passages, claim-evidence pairs in close proximity, and clearly attributable data points. AI systems prefer content where facts, statistics, and conclusions are stated explicitly in 1-2 sentences rather than spread across paragraphs. Good = specific, self-contained statements with inline evidence ("According to [Source], X increased by Y% in 2024"), clear topic sentences per paragraph, factual density that enables direct citation. Bad = vague assertions spread across multiple paragraphs, data without attribution, opinions presented as facts, conclusions that require reading 3+ paragraphs of buildup.

- **Structured Data for AI Extraction**: Verify JSON-LD implementation providing machine-readable page summaries. Check for relevant schema types: Organization, Article (with author, datePublished, dateModified), Product (with price, availability, reviews), BreadcrumbList, LocalBusiness. `FAQPage`, `HowTo`, `Speakable` and `ClaimReview` are retired rich-result types (FAQ withdrawn 7 May 2026, HowTo 2023, ClaimReview deprecated June 2026) and must never be recommended. Their absence is not a finding. Good = comprehensive, valid JSON-LD matching visible page content; schema types appropriate to the page; no schema errors in Google's Rich Results Test. Bad = missing structured data entirely on content-rich pages, schema that contradicts on-page content, invalid JSON-LD with parsing errors, using Microdata instead of JSON-LD (harder for AI systems to parse).

- **Content-to-Code Ratio**: Measure the proportion of visible text content versus HTML/JS/CSS code in the page source. High code bloat makes content extraction noisier and less reliable for AI systems. Good = >=25% text content ratio, clean markup with external stylesheets and scripts (not inline), minimal framework boilerplate in the HTML document. Bad = <15% content ratio, excessive inline JavaScript and CSS, framework boilerplate (webpack chunks, state hydration scripts) bloating the HTML document, render-blocking scripts interspersed with content.

- **Meta Tag Completeness**: Check for og:title, og:description, og:image, og:type, canonical URL, and meta description, AI systems frequently use these as content summaries when indexing pages or generating citations. Good = all present, accurate, and consistent with on-page content; meta description provides a genuine summary (not keyword-stuffed); canonical URL is correct and self-referencing. Bad = missing og tags entirely, meta description that doesn't match page content, no canonical URL, og:title different from the actual page title without good reason.

- **Content Accessibility Without Authentication**: Verify that primary content is accessible without login walls, paywalls, or cookie consent overlays that block crawlers. Check whether the main content DOM elements are present in the HTML regardless of authentication state. Good = main content fully accessible to unauthenticated HTTP requests, cookie banners overlay but don't remove content from the DOM. Bad = content behind login gates with no preview or summary, aggressive modals that replace content in the DOM (not just overlay), JavaScript-based access gates that prevent content rendering without cookies.

### Priority 3, Supporting Signals

- **Response Time for AI Crawlers**: Check server response speed and rate-limiting policies. AI crawlers may make many sequential requests; slow responses or aggressive rate limiting can prevent complete site indexing. Good = <500ms TTFB for content pages, no aggressive rate limiting for known bot user agents, graceful handling of concurrent requests. Bad = >2s TTFB, immediate 429 responses to bot user agents, CAPTCHAs triggered by crawler traffic patterns, Cloudflare or WAF challenges blocking known AI bots.

- **Robots Meta vs Robots.txt Consistency**: Verify no conflicting directives between page-level robots meta tags and site-level robots.txt rules. Conflicting signals create unpredictable crawl behavior. Good = consistent allow/disallow signals across both mechanisms; if robots.txt allows, page meta doesn't say noindex (unless intentional for specific pages). Bad = robots.txt allows a path but page-level meta tag says `noindex`, or robots.txt blocks a path that has `index, follow` meta tags; mixed signals suggesting uncoordinated configuration.

- **AI-Specific Meta Tags**: Note emerging tags like `ai-content-declaration`, `data-noai`, `data-ai-redact`, or similar signals that communicate AI-related content policies. These standards are nascent but growing. Good = intentional use of emerging standards where applicable, awareness of AI content policy declarations. Bad = not a penalty if absent, these are informational only, flag as opportunity for early adoption if relevant to the site's content strategy.

- **Robots.txt Crawl-Delay**: Check if crawl-delay directives are set and whether they are reasonable for AI bot traffic. Some sites set extremely high crawl-delays that effectively prevent indexing. Good = no crawl-delay or modest values (1-5 seconds) that allow reasonable crawl throughput. Bad = excessively high crawl-delay (>30 seconds) applied broadly, crawl-delay set specifically for AI bots at punitive levels while allowing search engine bots freely.

- **Sitemap Availability and Quality**: Verify XML sitemap exists, is referenced in robots.txt, and includes content pages with accurate `<lastmod>` dates. AI crawlers use sitemaps to discover and prioritize content. Good = comprehensive sitemap covering all indexable content pages, accurate lastmod dates, referenced in robots.txt. Bad = missing sitemap, sitemap with only a few pages while the site has hundreds, lastmod dates all identical (uninformative).

## Evaluation Framework

- **Critical**: Primary content entirely JavaScript-dependent with no SSR fallback (AI crawlers see empty pages); robots.txt accidentally blocks all AI crawlers via wildcard rules while intending to allow search engines; content trapped behind authentication with no accessible version for any crawler; empty HTML shell where 100% of content is loaded via client-side API calls.

- **High**: Missing structured data on content-rich pages (articles, products, FAQs); content-to-code ratio below 15% making extraction unreliable; key content inside iframes or shadow DOM inaccessible to standard HTML parsers; meta tags missing or contradicting page content; conflicting robots directives between page-level and site-level creating unpredictable crawl behavior.

- **Medium**: Suboptimal RAG chunk quality where sections lack self-containment but content is still accessible; no explicit AI bot rules in robots.txt while relying on defaults; citation-unfriendly content structure requiring multi-paragraph reading for any single fact; slow server response (1-2s TTFB); partial SSR with some non-critical content still client-rendered.

- **Low**: Missing emerging AI meta tags (these are not yet standardized); minor structured data gaps (e.g., missing optional schema fields like `dateModified`); crawl-delay slightly above optimal but not blocking; og:image missing while other og tags are present and correct; sitemap exists but has minor gaps in coverage.

## Common False Positives (DO NOT flag these)

- **Intentionally blocking AI crawlers**: Some sites deliberately disallow GPTBot, CCBot, or other AI crawlers to protect proprietary content or comply with content licensing agreements. This is a valid business decision. Report it as an informational observation noting which bots are blocked, but do not score it as an error or deficiency.

- **Login-required pages blocking crawlers**: Gated content (SaaS dashboards, premium articles behind paywall, user account pages) is expected to be inaccessible to all crawlers. Only flag if the public-facing marketing, informational, or blog pages, the content that should attract AI citations, are also gated.

- **No explicit AI bot rules in robots.txt**: If robots.txt has no AI-specific user-agent rules but also does not restrict general crawling (no broad `Disallow` for `*`), AI bots are allowed by default. This is the most common configuration and is perfectly fine. Only flag as an issue if general crawl access is restricted and AI bots are caught by broad disallow patterns they shouldn't be subject to.

- **Client-side interactivity via JS**: Interactive elements (search filters, calculators, sorting controls, dynamic charts, configurators) loading via JavaScript is fine and expected as long as the core informational content is in the initial HTML. Do not penalize JS-enhanced pages where the base content is server-rendered and JS adds interactivity on top.

- **Low content-to-code ratio on web application pages**: Dashboards, SaaS tools, interactive applications, and data visualization pages naturally have higher code-to-content ratios. Evaluate this signal only on content-focused pages (articles, product pages, landing pages, blog posts) where text content is the primary purpose.

## Page-Type Awareness

- **Homepage**: Verify that the value proposition, company name, tagline, and primary navigation are in static HTML. Structured data (Organization schema with name, logo, URL, social profiles) should be present. AI crawlers often use the homepage as the primary source for entity information about the company, ensure the homepage answers "who is [company]?" directly in the HTML.

- **Blog/Article Pages**: Highest priority for AI readiness, these are the most frequently cited content type in AI-generated responses. Full SSR is non-negotiable. Article schema (with author, datePublished, dateModified, headline) is essential. Clean heading hierarchy where every section is independently quotable. Ensure each H2/H3 section could be extracted as a standalone answer to a question.

- **Product Pages**: Product schema (JSON-LD with name, price, availability, reviews, images) is critical for AI shopping assistants and comparison engines. Key specs, pricing, and availability must be in static HTML, not loaded by JavaScript product widgets. Review content and aggregate ratings should be in structured data, not only rendered via third-party JS widgets.

- **FAQ Pages**: High AI citation potential, FAQ content directly matches question-answer patterns used in RAG retrieval. The value is in the visible content, not markup: FAQPage rich results are retired, so do not recommend the schema. Each Q&A pair must be self-contained; answers should be concise (2-4 sentences) and directly quotable without needing surrounding context or page navigation.

- **Documentation/Reference Pages**: Prime targets for RAG systems seeking technical information. Clean heading hierarchy is critical. Code blocks should have language annotations. Each section must be self-contained. Ensure documentation is not behind authentication gates. Consider providing raw markdown or plain-text versions alongside HTML for easier AI consumption.

- **Landing Pages**: Lower AI crawl priority but verify that core claims, features, and value propositions are accessible in static HTML. Aggressive A/B testing scripts, personalization layers, or dynamic content injection should not strip content from the base HTML that AI crawlers receive.

- **Legal Pages**: Low AI citation priority but should remain crawlable for compliance verification and entity information extraction. Ensure robots directives do not accidentally block these pages. Privacy policies and terms of service may be referenced by AI systems when answering questions about a company's data practices.

- **Resource/Tool Pages**: If the resource is content-based (datasets, reports, whitepapers), ensure the content is in static HTML, not only available as a PDF download or behind a form gate. AI crawlers cannot fill forms or parse PDFs reliably. Provide HTML versions of key data alongside downloadable formats.

## AI System Landscape

Understanding which AI systems crawl and how they use content informs the evaluation:

- **OpenAI (GPTBot, ChatGPT-User)**: GPTBot indexes content for training and retrieval. ChatGPT-User fetches pages in real-time when users share URLs or use browsing features. Both require accessible static HTML. GPTBot respects robots.txt; ChatGPT-User acts more like a browser but still relies on initial HTML quality.

- **Google (Google-Extended, Googlebot)**: Google-Extended controls whether content is used for Gemini and AI Overviews training (separate from standard search indexing via Googlebot). Blocking Google-Extended does NOT affect search rankings, it only affects AI training data. This distinction is important when advising on robots.txt configuration.

- **Anthropic (ClaudeBot, Claude-SearchBot, Claude-User)**: ClaudeBot crawls for training data; blocking it is purely a training decision with no effect on rankings or AI-answer visibility. Claude-SearchBot indexes for search quality, so blocking it removes the site from Claude's search answers. Claude-User serves user-initiated fetches. `anthropic-ai` and `Claude-Web` are retired names.

- **Common Crawl (CCBot)**: Operates the largest open web crawl used by many AI systems and researchers. Blocking CCBot affects a wide range of AI applications that rely on Common Crawl data, including some search engines and research tools.

- **Perplexity (PerplexityBot)**: Crawls for real-time AI search answers. Blocking PerplexityBot prevents the site from being cited in Perplexity search results, a direct visibility trade-off.

## Scoring Guidance

When scoring AI crawler readiness, prioritize signals that affect content accessibility (whether AI can see the content at all) over signals that affect extraction quality (how well AI can parse what it sees):

- **Tier 1, Accessibility**: Content in static HTML, SSR verification, authentication barriers. If AI crawlers cannot access the content, all other signals are irrelevant.

- **Tier 2, Extractability**: Clean HTML structure, RAG chunk quality, structured data, content-to-code ratio. These determine how accurately AI systems can parse and represent the content.

- **Tier 3, Discoverability**: Sitemap, robots.txt configuration, meta tags, response time. These affect whether AI systems find and prioritize the content but don't block access if the content is otherwise reachable.

- **Tier 4, Policy**: AI bot directives, emerging meta tags, crawl-delay. These represent intentional business decisions about AI engagement and should be reported as informational observations rather than scored as deficiencies.
