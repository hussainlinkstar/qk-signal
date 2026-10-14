# Skill: Schema & Structured Data Reviewer

## Purpose
Evaluate the correctness, completeness, and strategic deployment of Schema.org structured data (JSON-LD) across a website. This skill assesses whether the right schema types are applied to the right pages, whether properties are complete enough to trigger rich results, and whether schema data is consistent, valid, and free of common implementation mistakes.

## Signal Checklist

### Priority 1, Critical Signals
- **Page-Type to Schema Mapping**: Does each page have the correct schema types for its content? Required mappings:
  * Homepage → Organization, WebSite, (LocalBusiness if applicable)
  * Product page → Product, Offer, AggregateRating, Review, BreadcrumbList
  * Blog post → Article/BlogPosting, author Person, BreadcrumbList
  * FAQ page → no rich-result schema applies; FAQPage is retired. Judge the visible Q&A content.
  * Service page → Service, Organization, (LocalBusiness), BreadcrumbList
  * About page → Organization, Person (team members)
  * Contact page → Organization with contactPoint, LocalBusiness
  * Event page → Event, Place, Offer
  * Recipe page → Recipe, NutritionInformation
  * How-to page → no rich-result schema applies; standalone HowTo was withdrawn in 2023. Judge the visible steps.
  Good = Correct schema types present for the detected page type. Bad = Missing primary schema type entirely, or wrong schema type applied.
- **JSON-LD Validation**: Is the JSON-LD syntactically correct and properly structured? Good = Valid JSON, proper nesting, correct @context and @type declarations, no orphan blocks. Bad = Broken JSON syntax (unclosed brackets, trailing commas), missing @context, malformed nesting.
- **Schema Property Completeness**: Are required AND recommended properties filled, not just the type declared? Good = Product schema with name, description, image, offers (price, currency, availability), brand, and sku. Bad = Product schema with only name and @type, missing all properties that trigger rich results.
- **Schema Not Matching Visible Content**: Does the structured data accurately reflect what users see on the page? Good = Schema data matches visible content exactly (prices, ratings, descriptions). Bad = Schema declares data not visible to users (hidden ratings, prices that differ from displayed prices, fake reviews).

### Priority 2, High-Impact Signals
- **Rich Result Eligibility**: Based on current schema + content, which Google/Bing rich results are achievable? Good = Schema is complete enough to trigger eligible rich results (product snippets, FAQ dropdowns, how-to cards, review stars). Bad = Schema is present but missing required properties that prevent rich result triggering.
- **Cross-Page Schema Consistency**: Is Organization schema consistent across all pages? Good = Same Organization name, logo, url, and sameAs on every page that includes it. Bad = Different Organization names, logos, or urls on different pages.
- **Breadcrumb Schema vs Visual Breadcrumb Alignment**: Does the BreadcrumbList schema match the visible breadcrumb navigation? Good = Schema breadcrumb items exactly match visible breadcrumb links and hierarchy. Bad = Schema breadcrumbs differ from visual breadcrumbs, or breadcrumb schema exists with no visible breadcrumbs.
- **Schema.org Vocabulary Depth**: Are the most specific schema types used instead of generic ones? Good = SoftwareApplication instead of Thing, MedicalClinic instead of LocalBusiness, BlogPosting instead of CreativeWork. Bad = Generic types (Thing, CreativeWork, LocalBusiness) when more specific types are available and accurate.
- **Duplicate/Conflicting Schema Detection**: Are there multiple blocks of the same schema type with conflicting data? Good = Single, authoritative Organization block per page; one Product schema per product page. Bad = Two Organization blocks with different names or addresses; multiple Product schemas for a single product.

### Priority 3, Supporting Signals
- **AI-Extraction Schema**: Are schema types that aid AI understanding implemented where appropriate? Good = DefinedTermSet for glossaries, Organization and Product for entity facts, Article with author and dateModified. Bad = Missing these on content types where they would be highly valuable. `FAQPage`, `HowTo`, `Speakable` and `ClaimReview` are retired rich-result types (FAQ withdrawn 7 May 2026, HowTo 2023, ClaimReview deprecated June 2026) and must never be recommended. Their absence is not a finding.
- **Deprecated Schema Types**: Are any deprecated or outdated schema types in use? Good = Current schema vocabulary following Schema.org latest specifications. Bad = Using deprecated types or properties that search engines no longer support.
- **Schema Nesting Quality**: Are related schemas properly nested rather than declared as flat, disconnected blocks? Good = Product schema with nested Offer, AggregateRating, and Brand. Bad = Separate, disconnected Product and Offer blocks that don't reference each other.
- **SameAs and URL Linking**: Do entity schemas include sameAs properties linking to authoritative profiles? Good = Organization sameAs includes LinkedIn, Twitter/X, Facebook, Crunchbase, Wikidata URLs. Bad = No sameAs properties, or sameAs linking to inactive/incorrect profiles.

### CRITICAL RULE
If a schema type already appears in the audit's `schema_types_found` list, do NOT recommend implementing it. You MAY recommend IMPROVING it by adding missing properties. Always cross-check detected schema types against recommended schema types before making any recommendation. Recommending implementation of already-present schema is a critical error.

## Evaluation Framework
- **Critical**: Primary schema type for the page type is completely missing (e.g., no Product schema on a product page); JSON-LD is syntactically broken and unparseable; schema data contradicts visible content (deceptive markup).
- **High**: Schema type is present but missing required properties that prevent rich results; duplicate/conflicting schema blocks; breadcrumb schema mismatches visible navigation.
- **Medium**: Schema exists with required properties but missing recommended properties; generic types used instead of specific; no AI-extraction schemas on relevant content.
- **Low**: Minor property gaps; sameAs links could be more complete; nesting structure could be improved; deprecated but still functional types in use.

## Common Schema Mistakes (flag these when found)
- **FAQ schema that contradicts the page**: FAQPage markup applied to pages with no question-and-answer content. The rich result is retired so there is nothing to gain, and markup that disagrees with the visible page is a quality signal against the site.
- **Missing required properties**: Product without price/offers, Article without author/datePublished, Review without reviewRating. These prevent rich result eligibility.
- **Broken JSON-LD syntax**: Unclosed brackets, trailing commas after last array/object items, unescaped special characters in strings. These make the entire block unparseable.
- **Schema not matching visible content**: Ratings, prices, availability, or review counts in schema that don't match what's displayed on the page. Google treats this as structured data abuse.
- **Using deprecated schema types**: DataType declarations, legacy schema properties that have been superseded by newer alternatives.

## Common False Positives (DO NOT flag these)
- **Missing Product schema on category/listing pages**: Product schema belongs on individual product detail pages, not on category or product listing pages. Do not flag category pages for missing Product schema.
- **Recommending retired rich-result types**: never recommend adding FAQPage, HowTo, Speakable or ClaimReview. They no longer produce a rich result, so their absence is not a defect. Never recommend adding schema for content that does not exist either.
- **Missing Review schema when no reviews are displayed**: Review/AggregateRating schema must only be present when reviews are visually displayed on the page. Do not recommend Review schema for pages without visible reviews.
- **Incomplete LocalBusiness schema for non-local online businesses**: LocalBusiness schema is only relevant for businesses with physical locations serving local customers. Do not recommend it for SaaS, e-commerce, or digital-only businesses.
- **Missing Event schema when no events are listed**: Event schema should only be recommended when the page actually contains event information (dates, locations, ticket prices). Do not recommend it for pages that mention events in passing.

## Page-Type Awareness
- **Homepage**: Expect Organization + WebSite as minimum. Evaluate for WebSite SearchAction (sitelinks search box), Organization completeness, and optional LocalBusiness for physical businesses.
- **Product Pages**: Most schema-critical page type. Evaluate Product, Offer (with price, availability, currency), AggregateRating, Review, BreadcrumbList, and Brand nesting.
- **Blog Posts**: Expect Article or BlogPosting with author (Person), datePublished, dateModified, publisher (Organization), image, and BreadcrumbList.
- **FAQ Pages**: Judge the visible Q&A content, not markup. FAQPage rich results are retired, so do not expect the schema and do not flag it as missing. If FAQPage markup is already present, only flag it when it contradicts the visible content.
- **Service Pages**: Expect Service schema with provider (Organization), areaServed, serviceType, and description. BreadcrumbList for navigation context.
- **About Pages**: Expect Organization with detailed properties. Person schema for team members with jobTitle, sameAs, and image.
- **Contact Pages**: Expect Organization with contactPoint (telephone, email, contactType). LocalBusiness with geo coordinates and openingHoursSpecification for physical locations.
- **How-To Pages**: Judge the visible steps, not markup. Standalone HowTo rich results were withdrawn in 2023, so do not expect HowTo schema and do not flag it as missing. (`HowToStep` inside a `Recipe` is unaffected and still valid.)
- **Recipe Pages**: Expect Recipe with ingredients, instructions (HowToStep), cookTime, prepTime, nutrition (NutritionInformation), and image.
