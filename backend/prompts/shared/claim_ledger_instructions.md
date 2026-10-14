When a claim_ledger field is present in the schema, populating it is mandatory.

## What the Claim Ledger Is

The claim ledger is the inter-agent transfer protocol. Each entry represents one defensible assertion that a downstream critic or magistrate agent can evaluate, challenge, or approve. It is NOT a summary of findings, it is a structured list of specific, verifiable claims.

## Claim Types: Track A vs Track B

**Track A, Evidence-Based Claims** (preferred):
A claim directly supported by the Evidence Anchor or scraped page content.
- Must have at least one `evidence_refs` entry pointing to a specific data point.
- Example: "The LCP is 3.8s, which exceeds the 2.5s good threshold."
- Confidence should be 0.75-1.0.

**Track B, Prescriptive Claims** (use sparingly):
A recommendation that goes beyond direct evidence, it prescribes an action whose benefit cannot be directly measured from the current page data.
- Must still be grounded in SEO/AEO/GEO best practices and the page context.
- Must be plausible given the evidence, do not prescribe actions for content that does not exist.
- Example: "Adding a TL;DR block to the top of the article would improve AI extractability."
- Confidence should be 0.5-0.75.
- Track B claims are evaluated by the Track B Judge in the deep_judgment pipeline.

## Required Fields Per Claim

Every claim_ledger item MUST contain:
- `claim_id`: unique string identifier. Format: `{domain}-{sequence}`. Example: `seo-001`, `aeo-003`, `geo-007`.
- `domain`: the domain this claim belongs to. One of: `seo`, `aeo`, `geo`.
- `track`: `A` for evidence-based, `B` for prescriptive.
- `claim_text`: concise assertion, maximum 220 characters. State the specific finding, not the recommendation.
- `confidence`: float 0.0-1.0. Reflects how well the claim is supported by the evidence.
- `evidence_refs`: array of strings. Each string must reference a specific evidence source (e.g., `"lcp_value: 3.8s from CWV data"`, `"H1 reads: 'Welcome to Our Site'"`, `"schema_types_found does not include FAQPage"`). Maximum 3 refs per claim. Never invent refs.
- `severity`: one of `critical`, `high`, `medium`, `low`, `informational`.
- `recommended_action`: specific, concrete next step. Maximum 280 characters. Must be actionable enough for a critic to evaluate its validity.

## Claim Quality Rules

- Each claim must be falsifiable, a critic must be able to say "this is supported" or "this is not supported."
- Do not write claim_text in the form of a recommendation. Write it as an observation. The recommended_action is where the prescription goes.
- Do not repeat the same claim with different wording. If two findings overlap significantly, merge them into one claim.
- Do not produce more than 15 claims per domain. Focus on the highest-impact, most defensible claims.
- Cross-domain claims: if a finding is relevant to two domains, assign it to the primary domain and note the cross-domain relevance in recommended_action.

## Example Claim (Track A)

```json
{
  "claim_id": "seo-001",
  "domain": "seo",
  "track": "A",
  "claim_text": "LCP is 3.8s, exceeding the 2.5s good threshold by 52%. The LCP element is the hero image (1.2MB uncompressed PNG).",
  "confidence": 0.92,
  "evidence_refs": [
    "CWV data: lcp_value = 3.8s",
    "LCP element identified as hero-image.png, 1.2MB"
  ],
  "severity": "high",
  "recommended_action": "Compress hero image to WebP format targeting <200KB. Add explicit width/height attributes. Consider lazy loading below-fold images to prioritise LCP element."
}
```

## Example Claim (Track B)

```json
{
  "claim_id": "aeo-004",
  "domain": "aeo",
  "track": "B",
  "claim_text": "The main article has no TL;DR or summary block in the first 200 words, reducing AI answer extraction probability.",
  "confidence": 0.68,
  "evidence_refs": [
    "First 200 words of scraped content contain no direct answer pattern",
    "No summary heading detected in heading structure"
  ],
  "severity": "medium",
  "recommended_action": "Add a 40-60 word summary block immediately after the H1, using the format: '[Topic] is [definition]. [Key point 1]. [Key point 2].' This directly addresses conversational AI query patterns."
}
```
