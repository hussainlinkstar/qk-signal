import React from "react";
import Card from "@/components/ui/Card";
import type { SemanticVennNode } from "@/types/semanticFootprint";

type Props = {
  nodes: SemanticVennNode[];
};

export default function SemanticVenn({ nodes }: Props) {
  return (
    <Card className="p-4">
      <h3 className="text-base font-semibold text-(--t-1)">Semantic overlap</h3>
      {nodes.length === 0 ? (
        <p className="mt-3 text-sm text-(--t-2)">No overlap data available.</p>
      ) : (
        <ul className="mt-3 space-y-2 text-sm text-(--t-1)">
          {nodes.slice(0, 8).map((node) => (
            <li
              key={node.id}
              className="flex items-center justify-between rounded-lg bg-[color-mix(in_srgb,var(--panel)_50%,transparent)] px-3 py-2"
            >
              <span>{node.label}</span>
              <span className="text-(--t-2)">Overlap {Math.round(node.overlapScore * 100)}%</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
