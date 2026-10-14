Return ONLY valid JSON that matches the schema supplied by the caller.

## Hard Output Rules

- Do not return markdown.
- Do not wrap JSON in code fences (no ```json blocks).
- Do not add explanatory prose before or after the JSON object.
- Do not invent top-level keys that are not required by the schema.
- Preserve schema_version exactly when the schema requires it.
- Keep values concrete, audit-specific, and grounded in the supplied evidence.

## Field Value Rules

- String fields: never return an empty string `""` for required fields. If evidence is absent, return a brief statement of absence ("No data available for this metric in the audit scrape.").
- Numeric score fields (seo_score, geo_score, aeo_score): always return a float with one decimal place (e.g., 67.5, 42.0). Never return null for score fields, use 0.0 if no signals are present.
- Array fields (findings, recommendations, claim_ledger): return an empty array `[]` if no items exist, never return null.
- Boolean fields: always return true or false, never null.
- Null-allowed fields: only return null if the schema explicitly allows null AND the evidence is genuinely absent.

## When Evidence Is Absent

If a required output field has no supporting evidence in the audit data:
- Do NOT fabricate a value.
- Return the most conservative truthful value: 0.0 for scores, [] for arrays, a brief absence statement for strings.
- Do NOT omit required fields, always include every key the schema requires.

## JSON Integrity

- Ensure all strings are properly escaped (double quotes inside strings use `\"`).
- Ensure all arrays are properly terminated with `]`.
- Ensure the root object is a single JSON object `{}`, not an array.
- If the schema has nested objects, ensure they are all properly closed.
- Do not truncate output mid-JSON. If content would be very long, summarise within the JSON values rather than cutting off.


## Punctuation
- Never use em dashes or en dashes. Use commas, periods, or short separate sentences.
- Keep copy short and to the point.
