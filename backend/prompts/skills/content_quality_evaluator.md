# Skill: Content Quality Evaluator

## Purpose
Systematically evaluate the quality, depth, and trustworthiness of on-page content across E-E-A-T dimensions, readability, topical completeness, and editorial standards. This skill ensures content meets both user expectations and search-engine quality guidelines while identifying specific, actionable deficiencies rather than generic advice.

## Signal Checklist

### Priority 1, Critical Signals

- **E-E-A-T Compliance (Experience)**: Check for first-hand evidence such as original photos, personal anecdotes, case studies, product-usage demonstrations, or before/after comparisons. Look for language patterns indicating direct involvement ("I tested", "our team found", "after implementing"). Good = content shows direct, lived experience with the topic through concrete examples. Bad = generic advice with no evidence of hands-on knowledge, paraphrased information that could come from any secondary source.

- **E-E-A-T Compliance (Expertise)**: Check for author credentials, bylines with bios linking to professional profiles, topical depth that demonstrates specialist knowledge. Look for coverage of nuances, edge cases, and caveats that only a subject-matter expert would know. Good = author has verifiable qualifications (degrees, certifications, years of experience), content covers nuances a generalist would miss, includes technical precision without jargon overload. Bad = no author attribution, surface-level treatment indistinguishable from AI-generated filler, avoids complexity by staying only at introductory level.

- **E-E-A-T Compliance (Authoritativeness)**: Evaluate domain reputation signals, citations from peers, mentions in authoritative publications, industry awards, speaking engagements, or contributor credits at recognized outlets. Check whether the site is a go-to resource in its niche. Good = site is a recognized voice in its niche with external validation (linked-to by other authorities). Bad = no evidence of domain reputation, no external validation, content exists in isolation without peer acknowledgment.

- **E-E-A-T Compliance (Trustworthiness)**: Assess transparency (about page, contact info, editorial policy, corrections process), factual accuracy, disclosure of conflicts of interest (affiliate relationships, sponsorships), HTTPS implementation. Good = clear editorial standards, visible corrections policy, accurate claims, transparent affiliations, secure connection. Bad = anonymous content, no contact information, misleading claims, undisclosed affiliate relationships, HTTP without SSL.

- **Search Intent Alignment**: Verify the content format matches the dominant search intent for the target query. Cross-reference with SERP features, if Google shows featured snippets, the page should have concise answer blocks; if the SERP shows product carousels, the page should be transactional. Good = informational queries get comprehensive guides, transactional queries get product pages with CTAs, navigational queries land on the expected brand page, format matches SERP expectations. Bad = product page trying to rank for "how to" query, blog post for "buy X" intent, listicle for a query demanding in-depth analysis.

- **Duplicate/Thin Content Detection**: Flag pages with >70% content similarity to other pages on the same site or across the web. Measure boilerplate ratio and unique content percentage. Check for near-duplicate pages created by parameter variations, tag/category archives, or pagination. Good = >80% unique content per page, each page serves a distinct purpose. Bad = syndicated or scraped content, boilerplate-heavy pages with <30% unique text, multiple pages targeting the same keyword with overlapping content.

### Priority 2, High-Impact Signals

- **Information Density**: Assess ideas per paragraph and signal-to-filler ratio. Count substantive claims, data points, and actionable items per section. Flag filler patterns: vague superlatives ("best-in-class", "world-leading"), hedging language ("may", "could potentially"), and circular definitions. Good = every paragraph advances the topic with concrete information, data, or actionable advice; no sentence exists merely to fill space. Bad = marketing fluff, vague superlatives, hollow claims without supporting evidence, paragraphs that restate the heading without adding value.

- **Topical Depth vs Competitors**: Evaluate whether the page covers subtopics comprehensively, semantic completeness, entity coverage, related questions addressed. Compare against what top-ranking pages cover to identify gaps. Check for "People Also Ask" coverage and related entity mentions. Good = covers the topic more thoroughly than top-ranking competitors, addresses edge cases and related queries, includes entities and subtopics that establish semantic authority. Bad = superficial overview missing obvious subtopics that competitors cover, thin sections that gloss over important details, fails to address common follow-up questions.

- **Content Freshness**: Check for publication dates, "last updated" timestamps, temporal relevance of cited data and statistics. Evaluate update cadence relative to topic type, news/trends need frequent updates, evergreen topics need periodic accuracy reviews. Good = content has visible dates, statistics are current (within 1-2 years for fast-moving topics), update cadence matches topic volatility, historical data is clearly dated. Bad = undated content with stale statistics, references to outdated tools/methods/regulations, "2023 guide" still referencing 2020 data, no indication of when content was last reviewed.

- **Content Accuracy**: Verify that claims are verifiable, statistics are sourced and dated, no internal contradictions exist within the page. Check whether numerical claims match cited sources, whether advice aligns with current best practices, and whether comparisons are fair. Good = data points cite primary sources, claims are specific and falsifiable, advice is current and correct, comparisons use consistent methodology. Bad = unsourced statistics, round-number estimates presented as facts ("increases revenue by 300%"), contradictory statements within the same page, outdated advice presented as current.

- **Source Quality**: Evaluate outbound links, do they point to authoritative primary sources? Check link freshness (are linked sources still available and current?). Assess citation depth, does the page cite the original research or a summary of a summary? Good = links to peer-reviewed studies, official documentation, reputable news outlets, primary data sources; citations are current and accessible. Bad = broken outbound links, links to low-authority aggregator sites, no citations for factual claims, all sources older than 5 years on time-sensitive topics, citing secondary summaries instead of primary research.

### Priority 3, Supporting Signals

- **Readability**: Measure against Flesch-Kincaid grade level (<=9 for general audience content). Check paragraph length (<=4 sentences), subheading frequency (every 200-300 words), sentence length variation, and active vs passive voice ratio. Good = scannable structure, short paragraphs, clear language, varied sentence lengths, predominantly active voice, technical terms defined on first use. Bad = wall-of-text paragraphs exceeding 6 sentences, academic jargon for consumer audience, no subheadings for 500+ word stretches, monotonous sentence structure.

- **Multimedia Integration**: Check for images, videos, infographics, tables, charts, or interactive elements that support and extend the text content. All media should have descriptive alt text, captions, and serve an informational (not purely decorative) purpose. Good = media adds informational value (explains a concept visually, shows data trends, demonstrates a process), all properly annotated with alt text and captions, images are original or properly attributed. Bad = decorative stock photos with no alt text, no visual content on long-form pages (>1500 words), videos without transcripts, images that don't relate to surrounding text.

- **User Engagement Signals**: Evaluate content structure that encourages read-through, compelling hook in the introduction (first 2-3 sentences must communicate value), scannable subheadings that work as a standalone outline, visual variety breaking up text blocks, clear takeaways or summaries. Good = progressive disclosure, varied content blocks (text, lists, tables, callout boxes), summary/key-points sections, table of contents for long-form content. Bad = monotonous text blocks with no structural variation, buried lede (key information deep in the page), no structural incentive to continue reading, missing conclusion or summary.

- **Editorial Quality**: Check grammar, spelling, consistent tone, professional writing standards. Look for inconsistencies in formatting (heading styles, list formats, date formats), voice shifts (switching between formal and casual), and incomplete edits (tracked changes, placeholder text, "[TODO]" markers). Good = error-free prose, consistent voice and formatting throughout, polished presentation, no artifacts from editing process. Bad = typos in headings or prominent positions, inconsistent formatting, mixed tone (formal/informal switching), grammatical errors that impede comprehension, placeholder text left in production.

## Evaluation Framework

- **Critical**: E-E-A-T failures on YMYL (Your Money, Your Life) pages, medical advice without credentials, financial guidance without disclaimers, legal information that could mislead; duplicate or scraped content comprising >50% of the page; content that actively misinforms (wrong dosage, incorrect legal rights, dangerous DIY instructions); complete search-intent mismatch where the user gets the wrong content type entirely.

- **High**: Missing author attribution on expert topics; thin content (<300 words on topics requiring depth); stale content with outdated data actively affecting user decisions (old pricing, deprecated features, changed regulations); no citations for factual claims on informational pages; information density below 1 substantive claim per paragraph on average.

- **Medium**: Readability score above grade 12 for general audience; subheadings spaced >400 words apart; stock photos without alt text on content pages; minor factual inaccuracies that don't affect core advice; content freshness issues on non-critical topics (e.g., "best practices" guide 2+ years old but mostly still accurate).

- **Low**: Minor editorial issues (occasional typos in body text, inconsistent capitalization in subheadings); missing "last updated" date on evergreen content; outbound links to secondary rather than primary sources; slightly below-optimal information density in introductory sections; multimedia present but lacking captions.

## Common False Positives (DO NOT flag these)

- **Low word count on product pages**: Short, focused product descriptions (150-300 words) can be optimal. Product pages should prioritize specs, pricing, and CTAs over lengthy prose. Only flag if the page targets informational queries or competitors demonstrate that longer descriptions rank better.

- **No outbound links on legal pages**: Terms of service, privacy policies, and legal disclaimers are self-contained by nature. Absence of outbound links is expected and correct. The same applies to internal company announcements and press releases.

- **Low readability score on technical/academic content**: A Flesch-Kincaid grade level of 12+ is appropriate when the target audience is professionals, researchers, or specialists. Evaluate readability against the intended audience, not a universal benchmark. Medical journals, API documentation, and academic papers serve expert audiences.

- **Missing author bio on corporate pages**: Company-authored content (e.g., "By the [Brand] Team") is acceptable for corporate blogs, product announcements, and official communications. Only flag missing attribution on expert-opinion, advisory, or YMYL content where individual expertise matters.

- **Minimal multimedia on data/reference pages**: API documentation, specification sheets, data tables, and reference guides do not require images or videos. Evaluate multimedia need based on content type and whether visuals would genuinely aid comprehension.

- **Short paragraphs or bullet-heavy format**: Scannable, bullet-point-driven content is often optimal for how-to guides, listicles, comparison pages, and reference content. Do not penalize concise formatting that serves the content type and search intent.

- **Content seemingly "too short" on comparison pages**: Pages comparing two products/services may be concise (500-800 words) by design, focusing on key differentiators. Length alone is not a quality signal, evaluate whether the comparison is complete for its scope.

## Page-Type Awareness

- **Homepage**: Focus on value proposition clarity, trust signals (client logos, testimonials, certifications, media mentions), and navigational completeness. Content density expectations are lower, prioritize messaging hierarchy and user journey guidance over word count. E-E-A-T signals come from trust elements, not content depth.

- **Product/Service Pages**: Evaluate feature-benefit alignment, unique selling propositions, social proof (reviews, ratings, case study links), and CTA clarity. Topical depth should cover specs, use cases, pricing transparency, and differentiation from alternatives, not just marketing copy. Check for comparison tables and FAQ sections addressing buying objections.

- **Blog/Article Pages**: Full E-E-A-T evaluation applies. Expect author attribution with credentials, comprehensive topical coverage, supporting media, and source citations. This is where content quality standards are highest. Evaluate against top-ranking competitors for depth and completeness. Content freshness is critical for trending or time-sensitive topics.

- **Category/Hub Pages**: Evaluate internal linking completeness, brief but informative descriptions for linked content, and navigational utility. These pages serve as topic authorities, assess breadth of subtopic coverage and whether the page provides enough context to guide users to the right child page. Unique introductory content (150-300 words) should frame the category.

- **Contact/About Pages**: Trust signals are primary, verify real addresses, phone numbers, team bios with photos, company history, mission statement. Content quality here is about transparency and credibility, not depth or keyword optimization. Check for structured data (Organization, LocalBusiness schemas).

- **Legal Pages (Privacy, Terms)**: Evaluate clarity and completeness of legal obligations. Readability matters (plain language preferred over legalese where possible), but technical legal terminology is expected. Do not flag for low engagement, missing multimedia, or lack of keyword optimization.

- **Landing Pages**: Evaluate persuasion architecture, headline clarity, benefit statements, social proof, friction reduction, CTA prominence. Content should be conversion-optimized, not encyclopedic. Information density is measured by persuasive efficiency, not word count. Check for consistency between ad copy and landing page messaging.

- **FAQ Pages**: Evaluate answer completeness, question-answer format consistency, and coverage of common user queries. Answers should be self-contained (each Q&A makes sense independently). Judge the visible content only: FAQPage rich results are retired, so do not require or recommend the schema. Check whether questions reflect actual user search patterns, not just what the company wants to answer.

- **Resource/Tool Pages**: Evaluate whether the resource (calculator, template, checklist, dataset) delivers genuine utility. Content surrounding the tool should explain methodology, provide context, and demonstrate expertise. Thin wrapper pages around embedded third-party tools offer low content quality.

## Scoring Guidance

When scoring content quality, weight the signals by page importance and content type:

- **YMYL Pages (financial, medical, legal, safety)**: E-E-A-T signals carry 2x weight. Missing expertise or trustworthiness indicators on YMYL pages should always be scored as critical or high severity. Content accuracy is non-negotiable, even minor inaccuracies can cause real harm.

- **Commercial/Transactional Pages**: Search intent alignment and information density carry the highest weight. Product and service pages must answer the buyer's key questions (pricing, specs, comparisons, social proof) efficiently. Topical depth is measured by decision-support completeness, not word count.

- **Informational/Educational Pages**: Topical depth and source quality carry the highest weight. These pages compete on comprehensiveness and authority. Compare coverage against top-3 ranking competitors to establish the benchmark. Missing subtopics that competitors cover should be flagged as high severity.

- **Brand/Trust Pages (About, Contact, Team)**: Trustworthiness signals carry the highest weight. Evaluate whether the page establishes the entity's credibility, accessibility, and transparency. Content depth expectations are low, but accuracy and completeness of trust elements are critical.

## Interaction with Other Skills

- **SEO On-Page Auditor**: Content quality signals often overlap with on-page SEO (heading hierarchy, keyword placement, content depth). When both skills flag the same issue, content quality should focus on the user experience and information value, while the SEO auditor focuses on the technical ranking signal. Avoid duplicate findings, coordinate to ensure each issue is reported once with the most relevant framing.

- **AI Crawler Readiness**: Content quality directly affects AI citation potential. High-quality, citation-friendly content with clear claims and sourced data is more likely to be extracted and cited by AI systems. Content freshness and accuracy are especially important because AI models may propagate outdated or incorrect information at scale.

- **Link Authority Auditor**: Content quality drives natural link acquisition. Pages with high information density, original research, and comprehensive topical coverage attract editorial backlinks. When evaluating content, note whether the content has link-earning potential, this informs the link authority analysis.
