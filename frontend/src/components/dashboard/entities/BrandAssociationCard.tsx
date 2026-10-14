import React from "react";
import Card from "@/components/ui/Card";
import type { BrandAssociation } from "@/types/semanticFootprint";

type Props = {
  associations: BrandAssociation[];
  onSelectSourceUrl?: (url: string) => void;
};

export default function BrandAssociationCard({ associations, onSelectSourceUrl }: Props) {
  return (
    <Card className="p-6">
      <h3 className="text-xl font-bold tracking-tight text-(--t-1) mb-4">Brand associations</h3>
      {associations.length === 0 ? (
        <p className="mt-3 text-sm text-(--t-2)">No brand associations available.</p>
      ) : (
        <ul className="mt-3 space-y-2">
          {associations.slice(0, 6).map((item) => (
            <li
              key={item.brand}
              className="rounded-xl border border-(--line) bg-(--line-2) p-4 shadow-inner transition-colors hover:bg-(--line-2) text-sm text-(--t-1)"
            >
              <div className="flex items-center justify-between mb-2">
                <span className="font-bold text-(--t-1) text-base">{item.brand}</span>
                <span className="text-[10px] tracking-widest uppercase text-(--t-2) font-bold">
                  {item.sentiment}
                </span>
              </div>
              <p className="text-xs font-semibold text-(--t-2)">
                Strength: <span className="text-amber-500">{item.strength}</span>
              </p>
              <button
                type="button"
                className="mt-2 text-xs text-(--purple) underline"
                onClick={() => onSelectSourceUrl?.(item.sourceUrls[0] ?? "")}
              >
                Open source URL
              </button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
