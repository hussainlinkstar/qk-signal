"use client";

import React, { useMemo, useState } from "react";
import { Copy, Check } from "lucide-react";
import Button from "@/components/ui/Button";
import { GlassCard } from "@/components/ui/GlassComponents";

type EmbedCodeSnippetProps = {
  apiKey: string | null;
  origin?: string;
};

export default function EmbedCodeSnippet({ apiKey, origin }: EmbedCodeSnippetProps) {
  const [copied, setCopied] = useState(false);
  const hasRawKey = Boolean(apiKey);

  const snippet = useMemo(() => {
    const resolvedOrigin = origin || "https://qiko.ai/signal";
    const key = apiKey || "REPLACE_WITH_NEW_EMBED_KEY";
    const warning = apiKey
      ? ""
      : "<!-- Create a new Embed Key first. Raw keys are shown once and cannot be recovered later. -->\\n";
    return `${warning}<div id=\"thothgraph-audit-widget\"></div>\n<script src=\"${resolvedOrigin}/embed/widget.js\"\n  data-api-key=\"${key}\"\n  data-api-base=\"${resolvedOrigin}\"\n  data-theme=\"dark\"\n  data-button-text=\"Get Your Free Assessment\"></script>`;
  }, [apiKey, origin]);

  const copySnippet = async () => {
    try {
      await navigator.clipboard.writeText(snippet);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      setCopied(false);
    }
  };

  return (
    <GlassCard className="space-y-3 p-4">
      <div className="flex items-center justify-between gap-4">
        <p className="text-xs font-bold uppercase tracking-widest text-(--t-2)">Embed Snippet</p>
        <Button variant="ghost" size="sm" onClick={copySnippet}>
          {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
          {copied ? "Copied" : "Copy"}
        </Button>
      </div>
      <pre className="overflow-x-auto rounded-xl border border-(--border) bg-(--surface-subtle) p-3 text-xs text-(--t-2)">
        <code>{snippet}</code>
      </pre>
      {!hasRawKey ? (
        <p className="text-xs text-amber-300">
          No raw embed key available in this session. Create a new key and copy it when shown.
        </p>
      ) : null}
    </GlassCard>
  );
}
