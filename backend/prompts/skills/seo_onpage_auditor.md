# Skill: SEO On-Page Auditor

## Purpose
Systematically evaluate on-page SEO elements that directly influence search engine rankings, crawlability, and click-through rates. This skill teaches the auditor to assess content structure, metadata, internal linking, and semantic completeness with specificity grounded in the actual page.

## Signal Checklist

### Priority 1, Critical Signals

- **Title Tag**: Check length is 50-60 characters (max ~580px rendered width). Primary keyword should appear in the first 60 characters. Brand name should be positioned at the end after a separator (` | `, ` - `, `, `). Each page must have a unique title. Good = descriptive, keyword-leading, properly sized. Bad = missing, duplicate, truncated, keyword-stuffed, or generic ("Home", "Untitled").
- **Meta Description**: Check length is 150-160 characters. Must include a clear call-to-action or value proposition. Primary keyword should be present for bolding in SERPs. Must be unique per page. Good = compelling, CTA-driven, keyword-inclusive, proper length. Bad = missing, duplicate across pages, truncated mid-sentence, or stuffed with keywords.
- **H1 Tag**: Exactly one H1 per page. Must be descriptive and match the primary search intent for the page. Should NOT be identical to the title tag (complementary, not duplicated). Good = single, descriptive, intent-aligned H1. Bad = missing H1, multiple H1s, generic H1 ("Welcome"), or exact title duplicate.
- **Canonical Tag**: Must be present and self-referencing on canonical pages. Cross-domain canonicals must point to the correct authoritative version. Parameter URLs must canonicalize to the clean version. Good = correct self-referencing canonical. Bad = missing, pointing to wrong URL, or conflicting with other directives.
- **Indexability**: Check meta robots tag (index/noindex), X-Robots-Tag HTTP header, and robots.txt allowance. Ensure important pages are indexable and low-value pages are appropriately excluded. Good = intentional, consistent indexability directives. Bad = accidental noindex on key pages, conflicting directives, or robots.txt blocking critical resources.

### Priority 2, High-Impact Signals

- **Heading Hierarchy (H2-H6)**: Headings must follow sequential order without skipping levels (no H2 → H4). Should be keyword-rich and scannable, reflecting the content structure. Good = logical, sequential hierarchy with descriptive headings. Bad = skipped levels, single massive text block with no subheadings, or headings used purely for styling.
- **Internal Linking**: Evaluate anchor text quality (descriptive, not "click here"). Assess link equity flow to important pages. Identify orphan pages with no internal links pointing to them. Links must be contextually relevant within the surrounding content. Good = descriptive anchors, strategic equity flow, no orphan pages. Bad = generic anchor text, orphaned important pages, excessive footer/sidebar link farms.
- **Keyword Placement**: Primary keyword should appear in: title tag, H1, first 100 words of body content, URL slug, and at least one image alt text. Secondary keywords should appear in H2s and body content naturally. Good = natural keyword distribution across key positions. Bad = keyword absent from critical positions, or keyword-stuffed unnaturally.
- **URL Structure**: URLs should be short (<75 characters), descriptive, keyword-bearing, lowercase, hyphen-separated. No session IDs, tracking parameters, or unnecessary nesting. Proper canonicalization for parameter variants. Good = `/services/web-design`. Bad = `/page?id=1234&session=abc` or `/services/our-amazing-incredible-web-design-services-for-you`.
- **Topical Coverage**: Evaluate topic depth compared to top-ranking competitors. Check for semantic completeness, are all major subtopics covered? Identify content gaps where related topics are missing entirely. Good = comprehensive coverage that matches or exceeds competitor depth. Bad = thin content that barely scratches the surface, missing obvious subtopics.

### Priority 3, Supporting Signals

- **Image Optimization**: All meaningful images must have descriptive alt text reflecting the image content. Filenames should be descriptive (not `IMG_2031.jpg`). Explicit width/height attributes to prevent layout shifts. Lazy loading on below-fold images. Next-gen formats (WebP, AVIF) preferred. Good = descriptive alt text, proper dimensions, lazy-loaded, modern formats. Bad = missing alt text on meaningful images, generic filenames, no dimensions, eager-loading all images.
- **Open Graph / Twitter Card Meta**: Check for `og:title`, `og:description`, `og:image`, `og:url`, and `og:type`. Twitter Card meta (`twitter:card`, `twitter:title`, `twitter:description`, `twitter:image`) should be present. Image should be at least 1200x630px for optimal sharing. Good = complete OG and Twitter Card tags with quality images. Bad = missing entirely, or present but with broken image URLs or mismatched content.
- **Content Freshness**: Check for last modified date signals (HTTP headers, visible dates, schema `dateModified`). Evaluate temporal relevance, does the content reference current information? Assess update cadence for time-sensitive topics. Good = recent updates on time-sensitive content, visible dates, accurate dateModified. Bad = outdated statistics, references to past years as current, no freshness signals on YMYL content.
- **Semantic Gaps**: Identify missing subtopics that users would expect. Flag thin sections that need expansion. Note unanswered user questions that competitors address. Good = thorough coverage of user intent. Bad = obvious gaps where users must go elsewhere for complete information.

## Evaluation Framework

- **Critical Severity**: Missing or duplicate title tag, missing H1, accidental noindex on important pages, broken canonical pointing to 404, primary keyword absent from title AND H1 AND first 100 words.
- **High Severity**: Meta description missing or duplicated, heading hierarchy broken (skipped levels), important pages orphaned from internal linking, title tag severely truncated (>70 chars), missing canonical tag.
- **Medium Severity**: Title tag slightly over/under optimal length, generic anchor text on internal links, missing Open Graph tags, images without alt text, URL contains unnecessary parameters.
- **Low Severity**: Brand position in title not optimal, meta description slightly under optimal length, minor content freshness concerns, missing Twitter Card when OG is present, decorative images without alt text (informational only).

## Common False Positives (DO NOT flag these)

- **Missing meta description on paginated pages** (page 2, 3, etc.): Often intentional, search engines generate snippets from page content. Flag only if page 1 is also missing its meta description.
- **Multiple H1s on legacy CMS pages**: Many older CMS themes (WordPress pre-5.0, Drupal 7) output multiple H1s by design. Flag as informational with low severity, NOT as critical. Only critical if the page is newly built.
- **Short title tags on brand homepages**: A homepage title of "Nike" or "Apple" (5-6 chars) is an intentional branding choice, not an error. Only flag if the homepage title is generic like "Home" or "Welcome".
- **Missing alt text on decorative images**: CSS decorative elements, spacers, borders, and purely visual flourishes correctly use `alt=""` (empty alt). Do NOT flag empty alt on decorative images as an issue, this is correct accessibility practice.
- **Internal links in navigation/footer**: Repeated navigation links across all pages are normal site architecture. Do NOT flag these as "duplicate internal links", only evaluate contextual in-content links for quality.
- **Canonical tag pointing to HTTPS version from HTTP**: This is correct behavior during HTTPS migration. Do not flag as "mismatched canonical."

## Page-Type Awareness

- **Homepage**: Title can be shorter (brand-focused). H1 often brand-centric rather than keyword-centric. Internal linking is critical, homepage distributes link equity. Expect broad topical coverage, not deep single-topic focus.
- **Product/Service Pages**: Title must include product/service name + modifier (price, review, buy). Strong keyword placement is essential. Internal links to related products/categories matter. Schema (Product, Service) should complement on-page signals.
- **Blog/Article Pages**: Title should target long-tail keywords. Heading hierarchy is paramount for scannability. Content freshness and topical depth are primary evaluation criteria. Author attribution and datePublished matter.
- **Category/Listing Pages**: Title should include category + modifiers. H1 matches category name. Internal linking to child pages is critical. Thin content risk is high, evaluate for sufficient unique content beyond product listings.
- **Contact/About Pages**: Lower SEO priority, do not penalize for missing keyword optimization. Focus on local SEO signals (NAP consistency), structured data (Organization, LocalBusiness), and basic indexability.
- **Legal Pages (Privacy, Terms)**: Expect minimal SEO optimization. Do NOT penalize for missing keywords, thin meta descriptions, or lack of internal links. Only flag indexability issues (should typically be indexable but low priority).
