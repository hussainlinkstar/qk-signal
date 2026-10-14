## Evidence Anchor Interpretation Guide

The Evidence Anchor is injected above this section. It contains deterministic signals extracted from the audited page. These signals are ground truth, they take precedence over any LLM prior knowledge or assumption.

### How to Read the Evidence Anchor

**Core Web Vitals fields** (`lcp`, `cls`, `inp`, `fid`):
- Values are in seconds (LCP, FID) or fractions (CLS) or milliseconds (INP).
- A value of `null` means the metric was not measurable (JS-heavy SPA, too few real-user data points). Do NOT assume the metric is poor, state it was not measurable.
- Thresholds: LCP good <2.5s, needs improvement 2.5-4.0s, poor >4.0s. CLS good <0.1, needs improvement 0.1-0.25, poor >0.25. INP good <200ms, needs improvement 200-500ms, poor >500ms.

**Schema fields** (`schema_types_found`):
- This is an array of schema types detected on the page at audit time.
- CRITICAL: If a type appears in `schema_types_found`, you MUST NOT recommend implementing it. You may only recommend extending or improving it.
- Example: if `schema_types_found` contains `["Organization", "WebSite"]`, do not recommend adding Organization or WebSite schema. You may recommend adding missing properties to the existing Organization schema.

**Content signals** (`word_count`, `reading_time`, `thin_content`):
- `word_count`: total words on the page. Pages under 300 words are typically thin.
- `thin_content.is_thin`: if `true`, apply the thin content guard from `finding_quality_rules`.
- `reading_time`: estimated minutes to read. Context: blog posts typically 5-15 min, product pages 1-3 min.

**Meta signals** (`title_tag`, `meta_description`, `h1_tags`, `canonical_url`):
- `h1_tags` is an array. One H1 = correct. Zero H1 = missing. Two or more H1s = duplicate.
- `canonical_url` of `null` means no canonical tag is present.
- `title_tag` of `null` means the page has no title tag.

**Page type** (`page_type`):
- Values: `homepage`, `product`, `service`, `blog`, `article`, `category`, `contact`, `about`, `legal`, `faq`, `pricing`, `landing`, `unknown`.
- Adjust scoring expectations based on page type. Legal pages should score low on AEO/GEO. FAQ pages should score high on AEO if content is strong.

**Indexability** (`is_indexable`, `noindex_reasons`):
- If `is_indexable` is `false`, this is a critical SEO issue that likely explains poor organic performance.
- `noindex_reasons` lists why the page is excluded (meta robots, robots.txt, HTTP header).

**Scrape success** (`scrape_succeeded`):
- If `false`: the page could not be scraped. Do NOT generate findings based on assumed content. Only flag the crawlability/accessibility issue itself.
- If `true`: all content signals in the Evidence Anchor are based on real page data.

### Priority of Evidence

When the Evidence Anchor and your training knowledge conflict, ALWAYS trust the Evidence Anchor.

Examples:
- Evidence Anchor shows LCP = 1.8s → report good LCP, even if the page looks complex.
- Evidence Anchor shows `schema_types_found: ["FAQPage"]` → do NOT recommend FAQPage schema.
- Evidence Anchor shows `word_count: 85` → this is a thin page; apply thin content guard.
- Evidence Anchor shows `is_indexable: false` → this is a critical finding regardless of other signals.

### What to Do When Evidence Is Absent

If a specific metric is `null` or absent from the Evidence Anchor:
- Do NOT assume the metric is poor.
- Do NOT assume the metric is good.
- State "this metric was not available in the audit data" in the finding description.
- Assign a neutral or conservative score for that sub-dimension.
- Mark the finding confidence as lower (0.5-0.6) to reflect evidence absence.
