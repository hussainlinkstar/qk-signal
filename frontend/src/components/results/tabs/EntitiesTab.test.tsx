import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { tEn } from "@/test/i18nEn";
import EntitiesTab from "./EntitiesTab";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: tEn }),
}));

const baseEntitySummary = {
  total: 0,
  categorized: 0,
  avgConfidence: null,
  highConfidence: 0,
};

describe("EntitiesTab", () => {
  it("renders an upgrade lock notice instead of 'No entities detected' when the plan doesn't include entity extraction", () => {
    render(
      <EntitiesTab
        editableEntities={[]}
        entityChipSuggestions={[]}
        entitySummary={baseEntitySummary}
        lockedSection={{
          is_locked: true,
          required_plan: "plan_specialist",
          required_plan_label: "Specialist",
          detail: "Entity extraction and semantic node mapping are locked on the current plan.",
          lock_origin: "execution",
        }}
      />
    );

    expect(screen.getByText(/Entity extraction requires Specialist/i)).toBeInTheDocument();
    expect(screen.queryByText(/No entities found yet/i)).not.toBeInTheDocument();
  });

  it("renders the normal entity index and chips when not locked", () => {
    render(
      <EntitiesTab
        editableEntities={[{ name: "Qiko", type: "Organization", confidence: 0.9 }]}
        entityChipSuggestions={[]}
        entitySummary={{ total: 1, categorized: 1, avgConfidence: 90, highConfidence: 1 }}
      />
    );

    expect(screen.queryByText(/Entity extraction requires Specialist/i)).not.toBeInTheDocument();
    expect(screen.getByText("Qiko")).toBeInTheDocument();
  });

  it("still shows the genuine empty state (not a lock notice) when entities are simply empty and not locked", () => {
    render(
      <EntitiesTab
        editableEntities={[]}
        entityChipSuggestions={[]}
        entitySummary={baseEntitySummary}
      />
    );

    expect(screen.queryByText(/Entity extraction requires Specialist/i)).not.toBeInTheDocument();
    expect(screen.getByText(/No entities found yet/i)).toBeInTheDocument();
  });
});
