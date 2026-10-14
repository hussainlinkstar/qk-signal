import { headers } from "next/headers";

// ---------------------------------------------------------------------------
// SEC-02: Nonce-aware JSON-LD renderer (async server component).
//
// Reads the per-request CSP nonce from the `x-nonce` request header
// (set by middleware.ts) and injects it as the `nonce` attribute on the
// <script type="application/ld+json"> tag.  This satisfies the
// `script-src 'nonce-…'` CSP directive so JSON-LD blocks no longer
// trigger violations.
//
// Usage:
//   <JsonLd id="org-jsonld" data={organizationSchema} />
// ---------------------------------------------------------------------------

interface JsonLdProps {
  /** The structured data object (or array of objects) to serialize. */
  data: Record<string, unknown> | Record<string, unknown>[];
  /** Optional `id` attribute for the <script> element. */
  id?: string;
}

export default async function JsonLd({ data, id }: JsonLdProps) {
  const nonce = (await headers()).get("x-nonce") ?? "";

  return (
    <script
      type="application/ld+json"
      nonce={nonce}
      suppressHydrationWarning
      {...(id ? { id } : {})}
      // Defense-in-depth: escape angle brackets so that user-controlled
      // data can never inject a closing </script> tag or HTML comment
      // (<!--) that would break out of the JSON-LD block.  JSON parsers
      // understand \u003c / \u003e Unicode escapes, so the payload stays valid.
      dangerouslySetInnerHTML={{
        __html: JSON.stringify(data).replace(/</g, "\\u003c").replace(/>/g, "\\u003e"),
      }}
    />
  );
}
