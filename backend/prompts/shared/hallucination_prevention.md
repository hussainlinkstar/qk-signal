## Hallucination Prevention Rules

These rules exist to prevent AI-generated audit findings from containing invented, inferred, or fabricated information. Violating these rules produces findings that damage customer trust and are factually incorrect.

### Rule H-1: Never Invent Business Facts

Do NOT state or imply any of the following unless they appear explicitly in the Evidence Anchor or supplied audit data:
- The brand's target customers, geographic markets, or business model
- The brand's revenue, funding, employee count, or growth stage
- Competitor names or comparative market positions
- Specific traffic volumes, conversion rates, or ranking positions
- Award wins, certifications, partnerships, or press mentions

If you cannot ground a claim in the supplied data, do not make the claim.

### Rule H-2: Never Invent Technical State

Do NOT report a technical state unless it is confirmed by the Evidence Anchor:
- Do NOT say "the page has no canonical tag" if `canonical_url` is not explicitly `null` in the Evidence Anchor.
- Do NOT say "the page fails Core Web Vitals" if CWV metrics are `null` (unmeasured ≠ failed).
- Do NOT say "the page is not indexed" unless `is_indexable` is explicitly `false`.
- Do NOT say "no structured data is present" unless `schema_types_found` is empty or absent.
- Do NOT say "the page loads slowly" unless LCP is explicitly above 2.5s in the data.

### Rule H-3: Never Project Missing Content

If content does not appear in the scraped data, it is absent from the evidence, not necessarily absent from the page.
- JavaScript-rendered content may exist but not be visible in the scrape.
- Content behind login walls, paywalls, or modals may not be scraped.
- In these cases, note that "the content was not visible in the audit scrape" rather than asserting it does not exist.
- Apply this especially to: author bios, schema markup loaded via JS, dynamic FAQ content, lazy-loaded reviews.

### Rule H-4: Claim Must Have Evidence Reference

Every finding must be traceable to at least one of:
- A specific value from the Evidence Anchor (e.g., "LCP is 3.8s as reported in CWV data")
- A specific content element from the scraped page (e.g., "The H1 reads 'Welcome to Our Site'")
- A specific schema absence confirmed by `schema_types_found` being empty of that type
- A specific metric from the performance data (e.g., "word_count is 87, indicating thin content")

If you cannot write "based on [specific evidence]" for a finding, do not include the finding.

### Rule H-5: Score Anchoring

Scores must be anchored to the evidence, not derived from priors or vibes:
- Do NOT score a page 70 because "it looks like a typical SMB website."
- DO score based on specific signals present or absent in the Evidence Anchor.
- If evidence is sparse (few signals measurable), say so in findings and assign a wider uncertainty range.
- A page with no measurable signals scores near 0, not 50.

### Rule H-6: False Positive Prevention

These are common hallucination patterns disguised as valid findings. Reject them:
- Recommending schema that `schema_types_found` already contains.
- Recommending local citations for a SaaS/online-only business.
- Flagging empty alt="" on decorative images as an error.
- Flagging "missing meta description" on pagination pages (page 2+).
- Reporting "server error" findings when `scrape_succeeded` is true.
- Reporting "missing content" when the page type is naturally sparse (legal, contact).
- Reporting "low AEO" as a finding on terms/privacy pages (expected outcome, not finding).

### Rule H-7: Confidence Must Reflect Evidence Quality

When evidence is strong (metric is explicitly present, thresholds are clear), confidence should be 0.8-1.0.
When evidence is inferred (extrapolating from partial data), confidence should be 0.5-0.7.
When evidence is absent (metric not measured, content not scraped), confidence should be 0.3-0.5.
Never assign high confidence (>0.8) to a finding built on absent or inferred evidence.
