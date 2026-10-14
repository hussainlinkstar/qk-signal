## Finding Quality & Quantity Constraints

### Thin / Placeholder Page Guard
- Check the `thin_content` field in the Evidence Anchor. If `thin_content.is_thin` is `true`, the page has minimal or placeholder content.
- For placeholder pages (e.g. "No published case studies yet", "Coming soon"), do NOT generate findings that assume real content exists. Only produce findings about the page's structural readiness or suggest that content be created first.
- Do NOT recommend schema markup, structured data, or content optimization for content that does not yet exist on the page.
- For genuinely thin pages, limit findings to 1-3 high-level structural observations rather than the normal 5+ per domain.

### Minimum Finding Counts
- Produce **at least 5 findings per domain** (seo_findings, geo_findings, aeo_findings) when evidence supports it.
- A well-audited page should yield 6-12 findings per domain. Fewer than 5 per domain suggests incomplete analysis.
- Only produce fewer than 5 findings if the page is genuinely excellent in that domain (score > 85) or evidence is truly minimal.

### Finding Specificity
- Every finding must reference **specific elements** from the audited page (e.g. "The H1 tag reads 'Welcome' which is non-descriptive" not "Improve H1 tags").
- Avoid generic advice that could apply to any website. Findings must be grounded in the actual page content and structure.
- Where applicable, include the specific URL path, HTML element, schema type, or metric value that triggered the finding.

### Recommendation Quality
- Recommendations must be **actionable and specific**, state exactly what to change, add, or remove.
- Include expected impact: will this fix a critical blocker, improve ranking potential, or enhance AI extractability?
- Prioritize recommendations by their likely score impact: critical fixes first, then high-impact improvements, then nice-to-haves.

### Score Calibration Rubric
Use the full 0-100 numeric range for each score dimension. Scores must reflect granular, evidence-based evaluation, NOT coarse buckets.

**SEO Score (0-100)**:
- 90-100: Exceptional, all technical, content, and authority signals present
- 75-89: Strong fundamentals with minor gaps
- 60-74: Adequate core signals but clear improvement areas
- 40-59: Significant deficiencies, missing multiple key signals
- 20-39: Major issues, poor structure, thin content, or blocking errors
- 5-19: Critically broken, not indexable, severely penalized, or near-empty
- 0-4: No detectable SEO signals whatsoever

**GEO Score (0-100)** (Generative Engine Optimization):
- 90-100: Highly citation-worthy, strong entity + schema + localization
- 75-89: Good structure, minor gaps in entity markup or claim substantiation
- 60-74: Moderate readiness, some AI-extractable content but missing key signals
- 40-59: Weak GEO, poor structure, low entity density, minimal citation hooks
- 20-39: Very poor, content is opaque to generative engines
- 5-19: Almost no GEO signals
- 0-4: No GEO signals whatsoever

**AEO Score (0-100)** (Answer Engine Optimization):
- 90-100: Direct answers present, correct schema, high snippet readiness
- 75-89: Good Q&A patterns, some schema, mostly snippet-ready
- 60-74: Partial answer structures, incomplete schema
- 40-59: Weak, few direct answers, missing schema, poor extractability
- 20-39: Very weak, no answer patterns, no relevant schema
- 5-19: Almost no AEO signals
- 0-4: No AEO signals whatsoever

Use decimal precision (e.g. 67.5, 42.3). Score relative to the page's purpose and type.
A Terms/Privacy page should naturally score LOW on GEO/AEO (typically 5-25).
