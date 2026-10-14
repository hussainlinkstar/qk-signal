## Critique Rubric, Evaluation Framework for Critics & Magistrates

When reviewing findings, recommendations, and scores from generator agents, apply these concrete evaluation criteria:

### 1. Evidence Grounding
- **REJECT** any finding that cannot be traced to a specific element in the Evidence Anchor or supplied audit data.
- **REJECT** any recommendation that assumes business context not provided (e.g., inventing target keywords, competitor names, business goals, or geographic focus).
- **DOWNGRADE** findings that are technically correct but too generic to act on (e.g., "improve meta descriptions" without specifying which pages or what the current description says).
- **ACCEPT** findings that cite specific HTML elements, metric values, schema types, or content excerpts from the audit data.

### 2. Specificity Test
- **REJECT** findings that could apply to any website without modification. Every finding must reference something unique to the audited page.
- **DOWNGRADE** recommendations that say "consider" or "evaluate" without a concrete action. Good recommendations state exactly what to change, add, or remove.
- **ACCEPT** recommendations that include: the specific element to change, the current state, the recommended state, and the expected impact.

### 3. Schema Cross-Check
- **REJECT** any finding that recommends implementing a schema type already listed in `schema_types_found` in the Evidence Anchor.
- **ACCEPT** findings that recommend improving or extending an already-present schema type with specific missing properties.
- Verify that schema recommendations reference the correct Schema.org type for the detected page type.

### 4. Domain Boundary Compliance
- **REJECT** SEO findings that contain GEO or AEO recommendations (and vice versa). Each domain generator must stay in lane.
- **DOWNGRADE** to `cross_domain_note` style if a finding is relevant but belongs to another domain.
- Verify the domain exclusion list was respected, generators should not produce findings in excluded topic areas.

### 5. Score Calibration Audit
- **CHALLENGE** scores that cluster in the 50-70 range for all three domains, this suggests lazy calibration rather than genuine evaluation.
- **CHALLENGE** identical scores across SEO/GEO/AEO, each domain should reflect different strengths and weaknesses.
- **CHALLENGE** GEO/AEO scores above 30 for legal/terms/privacy pages, these page types should score low on generative optimization.
- **CHALLENGE** any score above 80 when the findings list contains 3+ critical-severity issues.
- **CHALLENGE** any score below 30 when all findings in that domain are low-severity or informational, a low score must be justified by at least one critical or high-severity finding.
- Verify decimal precision is used (not rounded to nearest 5 or 10).

### 6. Finding Count & Completeness
- **CHALLENGE** if fewer than 5 findings per domain are produced when evidence supports more, this suggests incomplete analysis.
- **CHALLENGE** if findings only cover surface-level issues (title tags, meta descriptions) while ignoring deeper signals (entity clarity, citation readiness, content architecture).
- Verify that the thin_content guard was respected, if the page is thin/placeholder, fewer findings are acceptable.

### 7. False Positive Detection
- **REJECT** findings that flag intentional design choices as errors (e.g., short brand-only homepage titles, missing FAQ schema on transactional pages, no AEO optimization on legal pages).
- **REJECT** findings that recommend schema for content that does not exist on the page.
- **REJECT** recommendations to add reviews/ratings schema when no reviews are displayed.

### 8. Contradiction Detection
- **REJECT** findings that contradict each other within the same domain (e.g., one finding says content is thin, another praises content depth).
- **REJECT** findings that contradict the Evidence Anchor metrics (e.g., claiming poor CWV when the evidence shows good CWV scores).
- Flag cross-domain contradictions for magistrate resolution.
