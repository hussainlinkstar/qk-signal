import React from "react";
import type { MissingAnswer } from "@/services/competitorsService";

type Props = {
  items: MissingAnswer[];
};

export default function MissingAnswers({ items }: Props) {
  if (items.length === 0) {
    return (
      <p className="text-sm text-(--t-2)">No missing answers found for the selected competitor.</p>
    );
  }

  return (
    <ul className="space-y-3 text-sm text-(--t-1)">
      {items.map((item) => (
        <li
          key={item.query}
          className="rounded-lg border border-[color-mix(in_srgb,var(--line)_70%,transparent)] p-3"
        >
          <p className="font-medium text-(--t-1)">{item.query}</p>
          <p className="mt-1 text-xs text-(--t-2)">Competitor citations:</p>
          <div className="mt-1 flex flex-wrap gap-2">
            {item.competitor_citations.map((citation) => (
              <span
                key={`${item.query}-${citation}`}
                className="inline-flex rounded-full border border-[color-mix(in_srgb,var(--purple)_40%,transparent)] bg-[color-mix(in_srgb,var(--purple)_20%,transparent)] px-2 py-1 text-xs text-(--t-1)"
              >
                {citation}
              </span>
            ))}
          </div>
        </li>
      ))}
    </ul>
  );
}
