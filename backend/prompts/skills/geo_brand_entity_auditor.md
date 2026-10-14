# Skill: GEO Brand Entity Auditor

## Purpose
Evaluate how well a brand's digital presence is structured for Generative Engine Optimization (GEO), ensuring that AI systems (ChatGPT, Gemini, Perplexity, Claude) can accurately identify, describe, and recommend the brand. This skill assesses entity clarity, authority signals, and cross-platform consistency that determine whether a brand is retrievable, citable, and trustworthy in AI-generated responses.

## Signal Checklist

### Priority 1, Critical Signals
- **Brand Entity Consistency**: Is the same brand name, description, and core attributes used across all digital properties? Good = Identical brand name, tagline, and description on website, social profiles, directories, and press. Bad = Name variations (e.g., "Acme Corp" vs "ACME" vs "Acme Corporation") with conflicting descriptions across platforms.
- **Machine-Readable Identity**: Does Organization schema provide comprehensive entity data? Good = Organization schema with name, url, logo, foundingDate, description, contactPoint, sameAs (linking all official profiles), areaServed, and knowsAbout properties. Bad = Minimal Organization schema with only name and url, or no Organization schema at all.
- **Knowledge Graph Signals**: Does the brand have Knowledge Panel presence and entity disambiguation? Good = Active Knowledge Panel with verified information, Wikidata item with complete properties, clear entity disambiguation from similarly named entities. Bad = No Knowledge Panel, no Wikidata presence, brand name conflicts with other entities.
- **E-E-A-T Entity Strength**: Are author and organizational credibility signals machine-readable? Good = Author pages with Person schema, credentials, and sameAs links; organizational about page with history, team, and credentials. Bad = No author attribution, anonymous content, no organizational credibility page.
- **LLM Retrieval Friendliness**: Is content structured for AI extraction with clear brand claim patterns? Good = "Brand X is a [category] company that [core value proposition]" stated clearly and early on key pages. Bad = Brand identity buried in marketing fluff, no clear extractable brand definition anywhere.

### Priority 2, High-Impact Signals
- **Authoritativeness Clues**: Are awards, certifications, memberships, and industry associations prominently displayed and marked up? Good = Awards section with dates, granting organizations, and structured data; certification logos with links to verification. Bad = No credibility signals, or awards mentioned only in passing without context.
- **Mentions / Corroboration Patterns**: Do independent sources confirm brand claims? Good = Press coverage from recognized outlets, expert citations, industry report mentions, third-party reviews. Bad = Only self-published claims, no external validation, all mentions are paid/sponsored content.
- **Prompt-Surface Coverage**: Is the brand visible for generative queries like "best X in Y", "top alternatives to Z", "what is [brand]"? Good = Content directly addresses comparison queries, alternative queries, and definitional queries about the brand. Bad = No content targeting how users ask AI about the brand or its category.
- **Brand SERP Ownership**: How much of page 1 does the brand control for branded queries? Good = Official site, social profiles, review platforms, and press coverage dominate branded SERP. Bad = Competitors, aggregators, or negative content dominate branded search results.
- **Knowledge Panel Optimization**: Is the Knowledge Panel claimed, verified, and attribute-complete? Good = Claimed panel with logo, description, social links, founding date, founders, and category. Bad = Unclaimed panel with auto-generated or incorrect information.
- **Digital PR Signal Density**: Are press releases, news mentions, expert quotes, and industry awards generating linkable authority? Good = Regular press coverage in industry publications, expert quote placements, award announcements. Bad = Zero press coverage, no industry mentions, no digital PR footprint.

### Priority 3, Supporting Signals
- **Wikipedia / Wikidata Entity Assessment**: Does the brand have a Wikipedia article and/or Wikidata item with complete properties? Good = Wikipedia article meeting notability guidelines, Wikidata item with comprehensive properties and citations. Bad = No Wikipedia/Wikidata presence (acceptable for smaller brands, see false positives).
- **Local Business Entity Signals**: For location-based businesses, is NAP (Name, Address, Phone) consistent across citations? Good = Identical NAP on Google Business Profile, website, Yelp, industry directories, and local citations. Bad = Conflicting addresses, phone numbers, or business names across directories.
- **Social Proof Inventory**: Are review platforms (Trustpilot, G2, Google Reviews, Capterra) present with quality signals? Good = Active profiles on 2+ review platforms, recent reviews, 4+ star average, management responses. Bad = No review platform presence, or only negative/outdated reviews.
- **Co-occurrence and Co-citation Patterns**: Does the brand co-appear with authoritative entities in its domain? Good = Brand mentioned alongside industry leaders in press, research, and comparison content. Bad = Brand only appears in isolation, no association with recognized entities.
- **Trust Signal Triangulation**: Do multiple independent sources agree on brand attributes? Good = Website, press, reviews, and directories all confirm the same brand attributes (founding date, location, offerings). Bad = Conflicting information across sources about basic brand facts.
- **AI Engine Brand Perception**: How do ChatGPT, Gemini, Perplexity, and Claude describe the brand when asked? Good = Accurate, positive, and consistent descriptions across AI engines. Bad = Inaccurate descriptions, confusion with other entities, or no recognition at all.
- **Multi-Modal Entity Presence**: Is the brand entity consistent across text, image, video, and audio? Good = Consistent logo across platforms, YouTube channel with branded content, podcast mentions. Bad = Inconsistent visual identity, no video/audio presence for a brand that should have it.

## Evaluation Framework
- **Critical**: Brand has no machine-readable entity definition (missing Organization schema); brand name is ambiguous with zero disambiguation signals; no extractable brand definition exists on the website.
- **High**: Organization schema exists but is minimal (name + url only); no Knowledge Graph presence; zero external corroboration of brand claims; E-E-A-T signals completely absent.
- **Medium**: Schema is present but incomplete (missing sameAs, knowsAbout, areaServed); limited press coverage; review platforms present but sparse; Knowledge Panel unclaimed.
- **Low**: Minor gaps, co-citation patterns could be stronger, multi-modal presence has gaps, Wikidata properties could be more complete, social proof could be more recent.

## Common False Positives (DO NOT flag these)
- **Missing Knowledge Panel for new/small brands**: Knowledge Panels require significant entity recognition from Google's Knowledge Graph. Do not flag a missing KP as critical for startups, new brands, or niche businesses, it is a long-term goal, not an immediate fix.
- **No Wikipedia article for niche businesses**: Wikipedia has strict notability guidelines. Most small-to-medium businesses will not qualify. Do not recommend "create a Wikipedia article" as an action item, recommend building notability signals instead.
- **Incomplete Organization schema on blog posts**: Organization schema belongs on the homepage, about page, and contact page. Do not flag individual blog posts for missing Organization schema, check for it site-wide on appropriate pages.
- **Low GEO score for content-only sites with no brand entity focus**: Recipe blogs, tutorial sites, and personal blogs are content entities, not brand entities. GEO brand scoring is less relevant, evaluate content quality instead.
- **Missing local citations for purely online businesses**: NAP consistency and local citations are irrelevant for SaaS companies, digital-only brands, and businesses with no physical location. Do not recommend Google Business Profile for non-local entities.

## Page-Type Awareness
- **Homepage**: Primary evaluation target for brand entity signals. Organization schema, brand definition, and value proposition must be machine-extractable here. This is the most important page for GEO.
- **About Page**: Secondary brand entity page. Evaluate for organizational history, team credentials (Person schema), founding story, and mission, all key Knowledge Graph inputs.
- **Product/Service Pages**: Evaluate for product entity clarity (Product/Service schema), brand-product relationship, and competitive positioning content that aids AI comparison queries.
- **Blog Posts**: Evaluate for author E-E-A-T signals (Person schema, author bio, credentials). Blog posts build topical authority that reinforces brand entity strength.
- **Press / News Page**: If present, evaluate for structured press mentions, award listings, and media coverage that corroborates brand claims.
- **Contact Page**: Evaluate for NAP consistency (local businesses only), contactPoint schema, and accessibility of brand contact information for AI extraction.
- **Legal / Terms Pages**: Skip GEO brand evaluation. These pages do not contribute to brand entity signals.
- **Landing Pages**: Evaluate for brand claim clarity and CTA-oriented brand positioning. Landing pages should reinforce, not contradict, the core brand entity definition.

## 2026 LLM Retrieval Context

### AI Brand Hallucination Risk
- Brands with low entity corroboration are more likely to be described inaccurately by AI systems. This is the core business risk of poor GEO.
- Evaluate: if an AI were asked "What does [brand] do?", would it answer correctly based on the content visible in the audit? If not, what is missing?
- High hallucination risk indicators: brand name shared with unrelated entities, inconsistent descriptions across digital properties, no Wikidata or Wikipedia presence, zero third-party corroboration.

### Google AI Overviews and GEO
- Google AI Overviews now surface brand information directly in search results for branded queries.
- Brands cited in AI Overviews have: Organization schema with sameAs links, multiple corroborating third-party sources, and clear entity definition on their homepage.
- The Knowledge Graph is the primary source for branded AI Overview content, brands with verified Knowledge Panel data have higher citation probability.

### Perplexity AI Brand Cards
- Perplexity shows brand information cards sourced from Wikidata and structured data.
- Brands without Wikidata Q-numbers miss Perplexity brand card display entirely.
- Evaluate: does the brand have a Wikidata item with at minimum: label, description, instance of (company type), website, and sameAs links to official profiles?

### ChatGPT and Bing Knowledge
- ChatGPT (via Bing integration) surfaces brand knowledge from Bing's entity graph.
- Bing Business profiles, Crunchbase listings, and LinkedIn company pages all feed Bing's knowledge graph.
- Press coverage indexed by Bing improves brand representation in ChatGPT responses.
- Evaluate: are the brand's key facts (what it does, where it's based, when it was founded) findable in Bing-indexed content?

### Claude and Training Data Representation
- Claude's knowledge of a brand depends on its training data (pre-cutoff), current content changes will affect future model generations.
- For current representation: the primary lever is ensuring accurate, consistent, and widely-distributed brand information across Bing-indexed and Google-indexed sources.
- Brands mentioned in Wikipedia, Crunchbase, Bloomberg, Reuters, and major industry publications have the best training data representation.

### LLM-Specific Schema Recommendations
- `ProfilePage` schema: for about pages and team pages, signals the page is about a real-world entity.
- `Organization.sameAs` with Wikidata URI (e.g., `https://www.wikidata.org/wiki/Q12345`): the single highest-impact GEO schema property for AI systems.
- `Organization.knowsAbout` with topic URIs: helps AI systems understand the brand's domain expertise.
- `Person.sameAs` with LinkedIn URL on author pages: directly feeds AI knowledge of who wrote content and their credentials.
