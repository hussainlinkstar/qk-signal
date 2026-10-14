"use client";

import React from "react";

import Card from "@/components/ui/Card";
import {
  fetchEntityGraph,
  mapGraphCategory,
  normalizeGraphPayload,
} from "@/services/semanticFootprintService";
import type { KnowledgeGraphPayload, SiteMapPayload } from "@/types/semanticFootprint";

type Props = {
  graphUrl?: string;
  graphPayload?: KnowledgeGraphPayload | null;
  siteMapPayload?: SiteMapPayload | null;
};

const deriveGraphFromSiteMap = (
  siteMapPayload: SiteMapPayload | null | undefined
): KnowledgeGraphPayload => {
  if (!siteMapPayload) {
    return normalizeGraphPayload(null);
  }

  const nodes = siteMapPayload.entities.map((entry) => {
    const category = mapGraphCategory(entry.category);
    return {
      key: `entity:${entry.normalizedKey}`,
      name: entry.name,
      type: category,
      category,
      normalized_name: entry.normalizedKey,
      sourceURLs: [],
    };
  });

  return normalizeGraphPayload({
    nodes,
    edges: [],
    categories: nodes.map((node) => node.category),
    url_mentions: [],
  });
};

export default function KnowledgeGraph({ graphUrl, graphPayload, siteMapPayload }: Props) {
  const [resolvedGraph, setResolvedGraph] = React.useState<KnowledgeGraphPayload>(() =>
    normalizeGraphPayload(graphPayload ?? deriveGraphFromSiteMap(siteMapPayload))
  );
  const [isLoadingGraph, setIsLoadingGraph] = React.useState(false);

  React.useEffect(() => {
    if (graphPayload) {
      setResolvedGraph(normalizeGraphPayload(graphPayload));
      return;
    }

    if (graphUrl) {
      let active = true;
      setIsLoadingGraph(true);
      void fetchEntityGraph(graphUrl)
        .then((payload) => {
          if (active) {
            setResolvedGraph(normalizeGraphPayload(payload));
          }
        })
        .finally(() => {
          if (active) {
            setIsLoadingGraph(false);
          }
        });

      return () => {
        active = false;
      };
    }

    setResolvedGraph(deriveGraphFromSiteMap(siteMapPayload));
  }, [graphPayload, graphUrl, siteMapPayload]);

  return (
    <Card className="p-4">
      <h3 className="text-base font-semibold text-(--t-1)">Knowledge graph snapshot</h3>
      {isLoadingGraph ? (
        <p className="mt-2 text-xs text-(--t-2)">Loading graph from endpoint...</p>
      ) : null}
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <div>
          <p className="text-xs uppercase tracking-wide text-(--t-2)">Nodes</p>
          <p className="text-2xl font-semibold text-(--t-1)">{resolvedGraph.nodes.length}</p>
        </div>
        <div>
          <p className="text-xs uppercase tracking-wide text-(--t-2)">Edges</p>
          <p className="text-2xl font-semibold text-(--t-1)">{resolvedGraph.edges.length}</p>
        </div>
      </div>
      <div className="mt-3 text-xs text-(--t-2)">
        <p>Categories: {resolvedGraph.categories.join(", ") || "Concept"}</p>
        <p>Relations: MENTIONED_IN, RELATED_TO</p>
      </div>
    </Card>
  );
}
