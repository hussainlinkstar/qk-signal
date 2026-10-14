import React from "react";
import Card from "@/components/ui/Card";
import type { KnowledgeGraphEdge, KnowledgeGraphNode } from "@/types/semanticFootprint";

type Props = {
  nodes: KnowledgeGraphNode[];
  edges: KnowledgeGraphEdge[];
};

export default function KnowledgeGraphPanel({ nodes, edges }: Props) {
  return (
    <Card className="p-4">
      <h3 className="text-base font-semibold text-(--t-1)">Knowledge graph snapshot</h3>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <div>
          <p className="text-xs uppercase tracking-wide text-(--t-2)">Nodes</p>
          <p className="text-2xl font-semibold text-(--t-1)">{nodes.length}</p>
        </div>
        <div>
          <p className="text-xs uppercase tracking-wide text-(--t-2)">Edges</p>
          <p className="text-2xl font-semibold text-(--t-1)">{edges.length}</p>
        </div>
      </div>
    </Card>
  );
}
