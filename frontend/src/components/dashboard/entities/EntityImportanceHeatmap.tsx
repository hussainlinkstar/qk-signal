import React from "react";
import Card from "@/components/ui/Card";
import type { EntityImportanceCell } from "@/types/semanticFootprint";

type Props = {
  cells: EntityImportanceCell[];
  onSelectSourceUrl?: (url: string) => void;
};

const tone = (score: number) => {
  if (score >= 80) return "bg-emerald-500/10 border-emerald-500/20 text-emerald-100";
  if (score >= 60) return "bg-amber-500/10 border-amber-500/20 text-amber-100";
  return "bg-rose-500/10 border-rose-500/20 text-rose-100";
};

export default function EntityImportanceHeatmap({ cells, onSelectSourceUrl }: Props) {
  return (
    <Card className="p-6">
      <h3 className="text-xl font-bold tracking-tight text-(--t-1) mb-4">
        Entity importance heatmap
      </h3>
      {cells.length === 0 ? (
        <p className="mt-3 text-sm text-(--t-2)">No entity importance records yet.</p>
      ) : (
        <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {cells.slice(0, 12).map((cell, index) => (
            <button
              key={`${cell.entity}-${index}`}
              type="button"
              className={`rounded-xl border p-4 text-left shadow-inner transition-colors hover:brightness-110 hover:bg-(--line-2) ${tone(
                cell.relevanceScore
              )}`}
              onClick={() => onSelectSourceUrl?.(cell.sourceUrl)}
            >
              <p className="font-bold text-(--t-1) text-base mb-1">{cell.entity}</p>
              <p className="text-[10px] tracking-widest uppercase text-(--t-2) mb-2">
                {cell.category}
              </p>
              <p className="text-xs font-semibold text-(--t-2)">
                Relevance: <span className="text-(--t-1)">{cell.relevanceScore}</span>
              </p>
            </button>
          ))}
        </div>
      )}
    </Card>
  );
}
