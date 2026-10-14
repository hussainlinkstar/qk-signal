import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import AuditEntitiesSection from "@/components/results/AuditEntitiesSection";
import { tEn } from "@/test/i18nEn";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: tEn }),
}));

const buildProps = (overrides: Record<string, any> = {}) => {
  const { auditForm: auditFormRaw, ...rest } = overrides;
  const auditFormOverrides = (auditFormRaw ?? {}) as Record<string, any>;
  return {
    auditForm: {
      handleEntityInputChange: vi.fn(),
      handleEntityInputKeyDown: vi.fn(),
      handleEntityInputBlur: vi.fn(),
      handleAddSuggestion: vi.fn(),
      removeEntity: vi.fn(),
      entitySuggestions: [],
      ...auditFormOverrides,
      form: { entities: [], entityInput: "", ...(auditFormOverrides.form ?? {}) },
    },
    isStartDisabled: false,
    entitySummary: { total: 0, categorized: 0, highConfidence: 0, avgConfidence: null },
    ...rest,
  } as any;
};

describe("AuditEntitiesSection", () => {
  it("is the approved Entity configuration section", () => {
    render(<AuditEntitiesSection {...buildProps()} />);

    expect(screen.getByRole("heading", { name: "Entity configuration" })).toBeInTheDocument();
    expect(
      screen.getByText("Alternative names the brand is known by, so mentions are matched to you.")
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Alternative names")).toBeInTheDocument();
  });

  it("always shows the match summary in the approved order", () => {
    render(
      <AuditEntitiesSection
        {...buildProps({
          entitySummary: { total: 2, categorized: 1, highConfidence: 5, avgConfidence: 91 },
        })}
      />
    );

    const labels = screen
      .getAllByText(/Names added|Strong matches|Average match|Type known/)
      .map((node) => node.textContent);
    expect(labels).toEqual(["Names added", "Strong matches", "Average match", "Type known"]);
    expect(screen.getByText("91%")).toBeInTheDocument();
  });

  it("reports no value rather than 0% when no confidence was measured", () => {
    render(
      <AuditEntitiesSection
        {...buildProps({
          entitySummary: { total: 1, categorized: 0, highConfidence: 0, avgConfidence: null },
        })}
      />
    );

    expect(screen.getByText("N/A")).toBeInTheDocument();
  });
});
