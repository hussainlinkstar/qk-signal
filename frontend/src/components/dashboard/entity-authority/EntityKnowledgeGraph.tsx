"use client";

import React, { useMemo, useState } from "react";

import { GlassCard } from "@/components/ui/GlassComponents";
import type {
  EntityGraphEdge,
  EntityGraphNode,
  EntityGraphResponse,
} from "@/types/entityAuthority";

type EntityKnowledgeGraphProps = {
  graph: EntityGraphResponse;
};

type PositionedNode = EntityGraphNode & { x: number; y: number };

const WIDTH = 900;
const HEIGHT = 440;
const PADDING = 36;

function categoryColor(category: string, isMissingTarget: boolean): string {
  if (isMissingTarget) {
    return "#f43f5e";
  }
  const normalized = category.toLowerCase();
  if (normalized === "person") return "var(--link)";
  if (normalized === "organization") return "var(--accent)";
  if (normalized === "product") return "var(--chart-4)";
  if (normalized === "concept") return "#8b5cf6";
  return "var(--muted-foreground)";
}

function layoutGraph(nodes: EntityGraphNode[], edges: EntityGraphEdge[]): PositionedNode[] {
  const sizedNodes = nodes.map((node, index) => {
    const angle = (index / Math.max(1, nodes.length)) * Math.PI * 2;
    return {
      ...node,
      x: WIDTH / 2 + Math.cos(angle) * 140,
      y: HEIGHT / 2 + Math.sin(angle) * 140,
    };
  });
  const byKey = new Map<string, PositionedNode>();
  sizedNodes.forEach((node) => byKey.set(node.key, node));

  const velocity = new Map<string, { vx: number; vy: number }>();
  sizedNodes.forEach((node) => velocity.set(node.key, { vx: 0, vy: 0 }));

  for (let step = 0; step < 120; step += 1) {
    for (let i = 0; i < sizedNodes.length; i += 1) {
      const a = sizedNodes[i];
      for (let j = i + 1; j < sizedNodes.length; j += 1) {
        const b = sizedNodes[j];
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const distance = Math.max(0.01, Math.sqrt(dx * dx + dy * dy));
        const force = 360 / (distance * distance);
        const fx = (dx / distance) * force;
        const fy = (dy / distance) * force;
        const va = velocity.get(a.key);
        const vb = velocity.get(b.key);
        if (!va || !vb) continue;
        va.vx -= fx;
        va.vy -= fy;
        vb.vx += fx;
        vb.vy += fy;
      }
    }

    for (const edge of edges) {
      const from = byKey.get(edge.from);
      const to = byKey.get(edge.to);
      if (!from || !to) continue;
      const dx = to.x - from.x;
      const dy = to.y - from.y;
      const distance = Math.max(0.01, Math.sqrt(dx * dx + dy * dy));
      const target = 110;
      const springForce = 0.008 * (distance - target);
      const fx = (dx / distance) * springForce;
      const fy = (dy / distance) * springForce;
      const fromVelocity = velocity.get(from.key);
      const toVelocity = velocity.get(to.key);
      if (!fromVelocity || !toVelocity) continue;
      fromVelocity.vx += fx;
      fromVelocity.vy += fy;
      toVelocity.vx -= fx;
      toVelocity.vy -= fy;
    }

    for (const node of sizedNodes) {
      const current = velocity.get(node.key);
      if (!current) continue;
      current.vx *= 0.82;
      current.vy *= 0.82;
      node.x = Math.max(PADDING, Math.min(WIDTH - PADDING, node.x + current.vx));
      node.y = Math.max(PADDING, Math.min(HEIGHT - PADDING, node.y + current.vy));
    }
  }

  return sizedNodes;
}

export default function EntityKnowledgeGraph({ graph }: EntityKnowledgeGraphProps) {
  const [selectedNodeKey, setSelectedNodeKey] = useState<string | null>(null);

  const positionedNodes = useMemo(
    () => layoutGraph(graph.nodes, graph.edges),
    [graph.edges, graph.nodes]
  );
  const nodeMap = useMemo(() => {
    const entries = positionedNodes.map((node) => [node.key, node] as const);
    return new Map(entries);
  }, [positionedNodes]);
  const selectedNode = selectedNodeKey ? (nodeMap.get(selectedNodeKey) ?? null) : null;

  if (graph.nodes.length === 0) {
    return (
      <GlassCard className="p-8 border-(--line) bg-(--line-2)">
        <h3 className="text-sm font-black uppercase tracking-[0.16em] text-(--t-2)">
          Knowledge Graph
        </h3>
        <p className="mt-3 text-sm text-(--t-2)">
          No graph entities were found for this project yet. Run a deep audit to generate the first
          map.
        </p>
      </GlassCard>
    );
  }

  return (
    <GlassCard className="p-6 border-(--line) bg-(--line-2)">
      <div className="mb-4 flex items-center justify-between gap-3">
        <h3 className="text-sm font-black uppercase tracking-[0.16em] text-(--t-2)">
          Knowledge Graph
        </h3>
        <p className="text-xs text-(--t-2)">
          {graph.nodes.length} nodes · {graph.edges.length} edges
        </p>
      </div>

      <div className="overflow-hidden rounded border border-(--line) bg-[color-mix(in_srgb,var(--panel)_80%,transparent)]">
        <svg
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          className="h-[420px] w-full"
          role="img"
          aria-label="Entity knowledge graph"
        >
          {graph.edges.map((edge) => {
            const from = nodeMap.get(edge.from);
            const to = nodeMap.get(edge.to);
            if (!from || !to) return null;
            return (
              <line
                key={`${edge.from}-${edge.to}-${edge.relation}`}
                x1={from.x}
                y1={from.y}
                x2={to.x}
                y2={to.y}
                stroke="rgba(148,163,184,0.35)"
                strokeWidth={Math.max(1, edge.thickness)}
              />
            );
          })}

          {positionedNodes.map((node) => {
            const selected = selectedNode?.key === node.key;
            const radius = Math.max(6, Math.min(14, node.node_size * 9));
            return (
              <g
                key={node.key}
                transform={`translate(${node.x} ${node.y})`}
                onClick={() => setSelectedNodeKey(node.key)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    setSelectedNodeKey(node.key);
                  }
                }}
                role="button"
                tabIndex={0}
                aria-label={`Entity ${node.name}`}
                className="cursor-pointer"
              >
                <circle
                  r={radius}
                  fill={categoryColor(node.category, node.is_missing_target)}
                  stroke={selected ? "var(--foreground)" : "rgba(255,255,255,0.25)"}
                  strokeWidth={selected ? 2.5 : 1.5}
                  strokeDasharray={node.is_missing_target ? "4 3" : undefined}
                />
                <text
                  x={radius + 6}
                  y={4}
                  fill={selected ? "var(--foreground)" : "rgba(226,232,240,0.92)"}
                  fontSize="11"
                  fontWeight={selected ? 700 : 500}
                >
                  {node.name}
                </text>
              </g>
            );
          })}
        </svg>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-3 text-xs text-(--t-2)">
        <LegendItem color="var(--link)" label="Person" />
        <LegendItem color="var(--accent)" label="Organization" />
        <LegendItem color="var(--chart-4)" label="Product" />
        <LegendItem color="#8b5cf6" label="Concept" />
        <LegendItem color="#f43f5e" label="Missing target" dashed />
      </div>

      {selectedNode && (
        <div className="mt-5 rounded-xl border border-(--line) bg-(--line-2) p-4">
          <p className="text-[11px] font-black uppercase tracking-wider text-primary">
            Entity Detail
          </p>
          <p className="mt-2 text-base font-semibold text-(--t-1)">{selectedNode.name}</p>
          <div className="mt-3 grid gap-2 text-xs text-(--t-2) md:grid-cols-4">
            <DetailItem label="Category" value={selectedNode.category} />
            <DetailItem label="Relevance" value={selectedNode.relevance_score.toFixed(1)} />
            <DetailItem label="Mentions" value={String(selectedNode.mention_count)} />
            <DetailItem label="Sources" value={String(selectedNode.sourceURLs.length)} />
          </div>
        </div>
      )}
    </GlassCard>
  );
}

function LegendItem({
  color,
  label,
  dashed = false,
}: {
  color: string;
  label: string;
  dashed?: boolean;
}) {
  return (
    <span className="inline-flex items-center gap-2">
      <span
        className="h-3 w-3 rounded-full border border-(--line) bg-(--c) [border-style:var(--bs)]"
        style={
          {
            "--c": color,
            "--bs": dashed ? "dashed" : "solid",
          } as React.CSSProperties
        }
      />
      {label}
    </span>
  );
}

function DetailItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[10px] font-black uppercase tracking-wider text-(--t-3)">{label}</p>
      <p className="mt-0.5 font-medium text-(--t-1)">{value}</p>
    </div>
  );
}
