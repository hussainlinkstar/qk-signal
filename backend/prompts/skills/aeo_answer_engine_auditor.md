# Skill: AEO Answer Engine Auditor

## Purpose
Evaluate how effectively a page's content is structured for extraction by answer engines (Google AI Overviews, ChatGPT, Perplexity, Gemini, Bing Copilot). This skill assesses whether content is formatted, phrased, and organized so that AI systems can confidently extract, attribute, and cite it as a direct answer to user queries.

## Signal Checklist

### Priority 1, Critical Signals
- **Answer Extraction Readiness**: Does the page contain direct, extractable answers to likely user queries? Good = Clear, self-contained answer within the first two paragraphs. Bad = Buried answers requiring multi-paragraph parsing, or no direct answer at all.
- **Explicit Question-Answer Formatting**: Are Q&A patterns present, question as heading, concise answer immediately below? Good = H2/H3 phrased as a question with a 40-60 word answer paragraph directly after. Bad = Questions implied but never explicitly stated, answers scattered across sections.
- **The 200-Word Rule**: Is the primary query answered within the first 200 words of the page? Good = Core answer delivered in the opening paragraph or a TL;DR block. Bad = 200+ words of preamble, history, or filler before the actual answer.
- **TL;DR Trust Block**: Is there a top-of-page summary combining author credentials with a direct answer? Good = Summary block with author name/expertise, date, and a 1-3 sentence definitive answer. Bad = No summary; the page starts with generic introductions or navigation elements.
- **Entity Clarity**: Are core entities named unambiguously with consistent terminology throughout? Good = "Next.js 14" used consistently, no vague "the framework" or "it" for first mentions. Bad = Vague pronouns, inconsistent naming (switching between "React Server Components", "RSC", "server components" without establishing equivalence).
- **Featured Snippet Format Readiness**: Is content formatted to match featured snippet patterns? Good = Paragraph answers 40-60 words, lists with 4-8 items, comparison tables with clear headers. Bad = Run-on paragraphs 200+ words, no list structures, data buried in prose.

### Priority 2, High-Impact Signals
- **Concise Claim Structure**: Does each paragraph contain exactly one idea with no filler? Good = Atomic paragraphs, each making a single verifiable claim with supporting evidence. Bad = Multi-idea paragraphs, hedging language, filler phrases ("It's important to note that...").
- **Source-Worthiness**: Does the content demonstrate expertise, freshness, and originality? Good = Author byline with credentials, publication date within 12 months, original data or research cited. Bad = No author, no date, rehashed content from other sources, no original insights.
- **Citation Friendliness**: Can AI systems easily extract quotable sentences with attribution? Good = Summary sentences that stand alone as citable claims, data points with clear attribution. Bad = All claims embedded in complex compound sentences, no standalone quotable statements.
- **Knowledge Block Quality**: Are answer sections self-contained and complete per subtopic? Good = Each H2/H3 section fully answers its subtopic without requiring context from other sections. Bad = Sections that start with "As mentioned above..." or require reading previous sections to understand.
- **Conversational Query Matching**: Are how/what/why/when patterns addressed in headings and content? Good = Headings like "How does X work?", "What is the cost of Y?", "Why choose Z over W?". Bad = Generic headings like "Overview", "Details", "More Information".
- **Semantic Triplet Density**: Are Subject-Predicate-Object structures present for knowledge graph ingestion? Good = "Django [subject] is a Python web framework [predicate-object] released in 2005 [additional triple]." Bad = Vague, relation-free prose: "There are many great options available in the market today."

### Priority 3, Supporting Signals
- **Voice Search Readiness**: Are concise, spoken-friendly answers available in natural language? Good = Answers phrased as complete spoken sentences (29 words average for voice results). Bad = Answers requiring visual context (tables, charts) or too long for spoken delivery.
- **AI Overview Eligibility**: Does the content carry signals that earn citation in Google AI Overviews? Good = Authoritative domain, well-structured content, clear claims backed by evidence. Bad = Thin content, no expertise signals, duplicate information available on stronger domains.
- **Information Density Scoring**: What is the signal-to-filler ratio? Good = 3+ distinct ideas per paragraph, no empty calorie phrases, high insight-per-word ratio. Bad = Paragraphs padded with "In today's fast-paced world...", "It goes without saying...", etc.
- **Multi-Turn Conversation Readiness**: Are follow-up queries anticipated and answered nearby? Good = After "What is X?", the next section covers "How much does X cost?" or "X vs Y comparison". Bad = Single-topic page with no anticipation of natural follow-up questions.
- **Schema for Answer Engines**: Are answer-oriented schema types implemented? Good = Article with author and dateModified, Organization, Product or Service, DefinedTermSet for glossaries. Bad = No schema at all on content-rich pages, or schema that contradicts the visible page. `FAQPage`, `HowTo`, `Speakable` and `ClaimReview` are retired rich-result types (FAQ withdrawn 7 May 2026, HowTo 2023, ClaimReview deprecated June 2026) and must never be recommended. Their absence is not a finding.
- **Zero-Click Content Optimization**: Is the content structured to answer directly in the SERP? Good = Definition + context in a single extractable paragraph, listicles with clear item structure. Bad = Content that requires click-through to understand, teaser-only visible content.
- **People Also Ask Capture Potential**: Does the page address question clusters with cascading Q&A structure? Good = Primary question answered, then 3-5 related questions addressed in subsequent sections. Bad = Only one question addressed, no related query coverage.

## Evaluation Framework
- **Critical**: No extractable answer exists for the page's primary target query; content completely fails the 200-word rule; zero Q&A formatting on content that should be answer-oriented.
- **High**: Answer exists but is buried (fails 200-word rule); no featured snippet formatting; entity naming is inconsistent causing extraction ambiguity.
- **Medium**: Answers are present but not optimally formatted; some Q&A structure but incomplete coverage; missing schema for answer engines; low information density.
- **Low**: Minor improvements possible, voice search phrasing could be tighter, PAA coverage could expand, semantic triplets could be more explicit.

## Common False Positives (DO NOT flag these)
- **Low AEO score on legal/terms pages**: Legal pages (Terms of Service, Privacy Policy, Cookie Policy) are not answer-oriented content. A low answer-extraction score is expected and correct, do not recommend Q&A formatting for legal text.
- **Recommending FAQPage or HowTo schema**: both are retired rich-result types. Never recommend adding them, on any page type, whether or not Q&A content exists.
- **No direct answer on navigational pages**: Homepages, category landings, and hub pages serve navigational intent. They are not designed to answer specific queries directly, do not flag for missing direct answers.
- **Low information density on opinion/editorial content**: Opinion pieces, editorials, and thought leadership articles serve a different purpose than informational content. Subjective prose is expected, not filler.
- **Missing TL;DR block on news articles**: News articles use the inverted pyramid structure where the lede IS the TL;DR. Do not recommend adding a separate summary block to properly structured news content.

## Page-Type Awareness
- **Homepage**: Evaluate brand entity answer (What is [brand]? What does [brand] do?), should be answerable from homepage content within 200 words. Do not expect Q&A formatting.
- **Product/Service Page**: Primary evaluation target. Should answer "What is [product]?", "How much does [product] cost?", "What are [product] features?". Featured snippet formatting is critical here.
- **Blog Post / Article**: Highest AEO potential. Evaluate full signal checklist. Expect Q&A headings, knowledge blocks, PAA coverage, and schema implementation.
- **FAQ Page**: Must have explicit Q&A formatting in the visible content. Evaluate answer conciseness (40-60 words per answer), question phrasing (natural language), and coverage completeness. Do not evaluate FAQPage schema: the rich result is retired.
- **Contact Page**: Minimal AEO relevance. Only evaluate if contact information is extractable (address, phone, hours) for local answer engines.
- **Legal / Terms Pages**: Skip AEO evaluation entirely. These pages serve compliance purposes, not answer engine optimization.
- **Landing Pages**: Evaluate for primary CTA query answering ("What is [offer]?", "How does [service] work?"). TL;DR trust block is critical here.

## 2026 AI Search Engine Context

### Google AI Overviews (SGE)
- AI Overviews cite content that: (a) appears on authoritative domains, (b) provides direct, factual answers, (c) is corroborated by multiple sources.
- Content cited in overviews typically has: clear subject-predicate-object claim structure, explicit author attribution, and is accessible without JavaScript.
- Evaluating AI Overview eligibility: look for multi-source corroboration signals (does the page cite industry data, external studies, or primary research?). Sole-source or brand-only content is less likely to be cited.
- AI Overviews often cite the "best" answer across multiple pages, evaluate whether this page's answer is more direct, more authoritative, or more comprehensive than what competitors likely offer given the page's topic area.

### Perplexity AI
- Perplexity favors pages with: explicit source attribution (author, publication, date), structured content with clear section boundaries, and content accessible to bots (no JS rendering required).
- Perplexity shows source cards, pages with Organization or Article schema have richer card display.
- Perplexity's citation model rewards pages with original data, specific statistics, and named experts.

### SearchGPT / OpenAI Browsing
- OpenAI favors clean HTML, minimal JavaScript rendering requirements, explicit headings, and structured data.
- Content with numbered steps, definition-first paragraphs, and comparison tables is preferred.
- Pages that answer "yes/no" questions with clear confirmation in the first sentence perform well.

### ChatGPT Browsing
- ChatGPT browsing (via Bing) prefers content that matches Bing's freshness and authority signals.
- Named entities with Schema.org Person or Organization markup improve attribution accuracy.
- Pages with datePublished and dateModified in schema are preferred for time-sensitive topics.

### Anthropic Claude Web Search
- Claude favors content with explicit factual claims backed by verifiable sources.
- Academic-style citation patterns (author, year, finding) are highly valued.
- Content with clear definitions and conceptual clarity is prioritized.

### AI Crawler Readiness
- Check robots.txt for the crawlers that decide citations (`OAI-SearchBot`, `Claude-SearchBot`, `PerplexityBot`) and, separately, the training crawlers (`GPTBot`, `ClaudeBot`, `Google-Extended`). Blocking a training crawler does not affect AI-answer eligibility; blocking a search crawler does. `Googlebot` is ordinary search indexing, not an AI crawler.
- Content blocked from AI crawlers cannot be cited in AI-generated answers, this is a critical AEO issue.
- JavaScript-only rendered content (CSR without SSR) is invisible to most AI crawlers, evaluate based on scrape success and content accessibility signals.
