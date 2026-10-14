## Schema Awareness (MANDATORY)

Check the `schema_types_found` list in the Evidence Anchor above.

CRITICAL RULES for schema/structured-data recommendations:
- If a schema type (e.g. Organization, WebSite, FAQPage, SoftwareApplication, Article) already appears in `schema_types_found`, do NOT recommend "implementing", "adding", or "deploying" that type. It is already present on the page.
- You MAY recommend IMPROVING or EXTENDING an already-present schema type (e.g. adding missing required properties), but you must explicitly state that the type already exists and specify which properties need enhancement.
- Only recommend implementing schema types that are genuinely ABSENT from `schema_types_found`.
- When referencing schema in a finding or recommendation, always cross-check against `schema_types_found` first.