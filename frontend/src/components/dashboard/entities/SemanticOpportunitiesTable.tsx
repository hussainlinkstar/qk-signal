import React from "react";
import Card from "@/components/ui/Card";
import type { SemanticOpportunity } from "@/types/semanticFootprint";

type Props = {
  rows: SemanticOpportunity[];
  onSelectSourceUrl?: (url: string) => void;
};

export default function SemanticOpportunitiesTable({ rows, onSelectSourceUrl }: Props) {
  return (
    <Card className="p-6">
      <h3 className="text-xl font-bold tracking-tight text-(--t-1) mb-4">Semantic opportunities</h3>
      {rows.length === 0 ? (
        <p className="mt-3 text-sm text-(--t-2)">No semantic opportunities identified.</p>
      ) : (
        <div className="mt-4 overflow-x-auto rounded-xl border border-(--line) shadow-inner">
          <table className="min-w-full text-left text-sm text-(--t-1)">
            <thead className="bg-(--line-2) text-[10px] font-bold tracking-widest uppercase text-(--t-2)">
              <tr>
                <th className="px-4 py-3">Entity</th>
                <th className="px-4 py-3">Category</th>
                <th className="px-4 py-3">Score</th>
                <th className="px-4 py-3">Action</th>
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, 10).map((row) => (
                <tr
                  key={row.id}
                  className="border-t border-(--line) transition-colors hover:bg-(--line-2)"
                >
                  <td className="px-4 py-3 font-semibold text-(--t-1)">{row.entity}</td>
                  <td className="px-4 py-3 text-[10px] tracking-widest uppercase text-(--t-2) font-bold">
                    {row.category}
                  </td>
                  <td className="px-4 py-3 text-thoth-brass font-semibold">
                    {row.opportunityScore}
                  </td>
                  <td className="px-4 py-3">
                    <button
                      type="button"
                      className="text-(--purple) underline"
                      onClick={() => onSelectSourceUrl?.(row.sourceUrls[0] ?? "")}
                    >
                      Drill-down URL
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
