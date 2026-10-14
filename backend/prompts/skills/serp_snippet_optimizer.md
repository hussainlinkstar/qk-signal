# Skill: SERP Snippet Optimizer

## Purpose
Evaluate a page's readiness to win enhanced SERP visibility through optimized snippets, rich results, featured snippets, and other search result features. This skill focuses on maximizing click-through rate and search result real estate.

## Signal Checklist

### Priority 1, Critical Signals

- **Title Tag SERP Display**: Rendered pixel width should stay under ~580px for desktop (~480px mobile) to avoid truncation. Primary keyword should be visible without truncation. Brand placement at the end preserves keyword visibility. Evaluate emotional and CTR triggers, numbers, power words ("Ultimate", "Complete"), current year, brackets [2025]. Good = full title visible in SERP, keyword-leading, CTR-optimized. Bad = title truncated mid-word, keyword cut off, no differentiating elements.
- **Meta Description SERP Display**: Check truncation risk at ~920px desktop (~680px mobile). Must contain a clear call-to-action ("Learn how", "Get started", "Compare options"). Unique value proposition that differentiates from competing results. Keywords present for Google bolding effect. Good = compelling, complete description with CTA and keyword bolding. Bad = truncated mid-sentence, no CTA, generic text indistinguishable from competitors.
- **Rich Snippet Opportunities**: Evaluate eligibility for: Review stars (AggregateRating), Price and availability (Product/Offer), Recipe cards (Recipe schema), Event details (Event schema), Breadcrumb trail (BreadcrumbList schema). FAQPage and HowTo no longer produce rich results (FAQ withdrawn 7 May 2026, HowTo 2023) and must not be offered as opportunities. Check if required schema properties are present and valid. Good = eligible schema implemented with all required properties. Bad = eligible content without corresponding schema, or schema with missing required fields.
- **Featured Snippet Targeting**: For paragraph snippets: identify a clear question + concise 40-60 word answer within the first paragraph or under a question-form heading. For list snippets: content should use ordered/unordered lists with 4-8 items. For table snippets: data presented in HTML `<table>` format with clear headers. For answer boxes: direct, factual answers to common questions. Good = content structured for snippet extraction with clear question-answer patterns. Bad = answers buried in long paragraphs, no question-form headings, information not structured for extraction.

### Priority 2, High-Impact Signals

- **Sitelinks Optimization**: Clear, descriptive main navigation enables sitelinks. Site architecture should have a logical hierarchy. Internal anchor text must be descriptive (not "Page 1", "Link"). Search Console sitelinks demotions should be reviewed. Good = clear nav structure with descriptive labels, logical hierarchy. Bad = flat site structure, generic navigation labels, critical pages buried deep.
- **People Also Ask Alignment**: Content should include question-form headings (H2/H3) matching common PAA queries. Answers should be concise (2-3 sentences) directly below the question heading. Build topical clusters that cover related questions comprehensively. Good = question-form headings with concise answers, covering multiple related PAA queries. Bad = no question-form content, long-winded answers without clear extraction points.
- **Knowledge Panel Influence**: Implement Organization or Person schema with complete properties. Ensure brand name consistency across the site and external sources. Use `sameAs` links to authoritative profiles (LinkedIn, Wikipedia, Crunchbase, social media). Good = complete entity markup, consistent branding, sameAs links to authoritative sources. Bad = no entity schema, inconsistent brand naming, no external profile linking.
- **Breadcrumb Display**: Implement BreadcrumbList schema with correct hierarchy. URL structure should mirror breadcrumb path. Each breadcrumb item needs both `name` and `item` (URL) properties. Good = valid BreadcrumbList schema matching URL hierarchy. Bad = missing breadcrumb schema, hierarchy mismatch with URL structure, missing item URLs.

### Priority 3, Supporting Signals

- **Image Pack Eligibility**: Images should have descriptive filenames (not `DSC_0001.jpg`). Alt text must accurately describe the image and include relevant keywords naturally. Implement ImageObject schema where appropriate. Include images in an image sitemap for discovery. Good = descriptive filenames, keyword-rich alt text, image schema, image sitemap. Bad = generic filenames, missing alt text, no image sitemap, images blocked by robots.txt.
- **Video Carousel Opportunity**: Implement VideoObject schema with required properties: `name`, `description`, `thumbnailUrl`, `uploadDate`, `contentUrl` or `embedUrl`, `duration`. For YouTube-hosted videos, optimize title, description, and chapters (key moments). Provide video transcript for accessibility and indexability. Good = complete VideoObject schema, quality thumbnails, key moments marked. Bad = video on page without any schema, missing thumbnail, no duration specified.
- **Mobile SERP Considerations**: Titles truncate earlier on mobile (~480px vs ~580px desktop). Descriptions are shorter on mobile (~680px vs ~920px). Passage indexing can surface specific sections, ensure key passages are self-contained and clearly headed. Continuous scroll on mobile means position 1-10 all get impressions. Good = title and description optimized for mobile truncation points, clear passage structure. Bad = key information truncated on mobile, passages not self-contained.

## Evaluation Framework

- **Critical Severity**: Title tag truncated so severely that primary keyword or brand is not visible in SERP, eligible rich results completely unimplemented (e.g., product page with no Product schema), structured data with validation errors preventing rich result display.
- **High Severity**: Meta description missing or truncated mid-sentence, featured snippet opportunity clearly missed (question-form content exists but not structured for extraction), breadcrumb schema missing on deep-hierarchy site.
- **Medium Severity**: Title tag could be more CTR-optimized (missing year, numbers, or power words), Knowledge Panel opportunities not fully leveraged, PAA-style questions present but answers too verbose, image pack opportunities missed due to poor alt text.
- **Low Severity**: Minor title truncation (last 1-2 characters), Twitter Card missing when OG is present, video schema incomplete but video is present, sitelinks could be improved with better navigation labels.

## Common False Positives (DO NOT flag these)

- **No FAQ rich result for transactional pages**: Google rarely displays FAQ rich results for buy-intent queries (product pages, checkout flows, pricing pages). Do NOT recommend FAQPage schema on purely transactional pages, it won't trigger rich results and clutters the markup.
- **Missing video schema when no video exists**: Do NOT recommend adding video content solely to gain video carousel visibility. Only flag missing video schema when a video is already present on the page but lacks structured data.
- **Short meta description on navigational pages**: Brand homepages and navigational landing pages often have intentionally short or absent meta descriptions, letting Google generate the snippet from page content. Only flag if the auto-generated snippet is poor quality.
- **No featured snippet optimization on YMYL topics**: Google is cautious about featured snippets for Your Money Your Life queries (medical, financial, legal). Do not treat missing featured snippet capture as a failure for YMYL content, it may be algorithmically suppressed.
- **Missing AggregateRating on new products**: Products without reviews should NOT have AggregateRating schema. Do not flag the absence of review stars for products with zero reviews, adding empty ratings violates Google guidelines.

## Page-Type Awareness

- **Homepage**: Focus on sitelinks optimization and Knowledge Panel influence. Title should be brand-forward. Rich snippets are typically less relevant. Organization schema is the priority structured data.
- **Product Pages**: Rich snippets (price, availability, reviews) are the highest priority. Product schema with Offer is essential. Featured snippets are less common for product pages, focus on rich result features instead.
- **Blog/Article Pages**: Featured snippet targeting is the primary focus. PAA alignment is critical. Article schema with author and date enhances SERP display. Question-form headings with concise answers maximize snippet eligibility.
- **FAQ/Support Pages**: Featured snippet eligibility is high for how-to and troubleshooting queries, so the win is in question-shaped headings and concise self-contained answers. FAQPage markup is not: the rich result is retired, so do not recommend it.
- **Local/Service Pages**: Local business rich results (hours, rating, phone) are the priority. Breadcrumb display matters for multi-location sites. Review schema for service pages can trigger star ratings.
- **Category/Listing Pages**: Breadcrumb display is essential for navigation context in SERPs. Sitelinks and site hierarchy signals matter most. Featured snippets are possible for "best of" or comparison category pages.
