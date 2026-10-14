import React from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { tEn } from "@/test/i18nEn";
import AuditReport from "@/components/results/AuditReport";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: tEn }),
}));
import {
  reportWithEmptyEntitiesFixture,
  reportWithGroundingFixture,
  reportWithHighConfidenceDebateFixture,
  reportWithEntitiesFixture,
} from "@/components/results/__fixtures__/auditReportFixtures";

vi.mock("html2canvas", () => ({
  default: vi.fn(),
}));

vi.mock("jspdf", () => ({
  default: vi.fn().mockImplementation(() => ({
    internal: { pageSize: { getWidth: () => 210, getHeight: () => 297 } },
    setFontSize: vi.fn(),
    setTextColor: vi.fn(),
    text: vi.fn(),
    addImage: vi.fn(),
    addPage: vi.fn(),
    save: vi.fn(),
  })),
}));

describe("AuditReport canonical rendering", () => {
  it("renders canonical scores, recommendations, and entities", () => {
    render(<AuditReport report={reportWithEntitiesFixture} />);

    expect(screen.getByText("Current Metrics")).toBeInTheDocument();
    expect(screen.getByText("Fix missing schema markup")).toBeInTheDocument();
    expect(screen.getByText(tEn("signalAuditReport.entities.chipsTitle"))).toBeInTheDocument();
    const entitySection = screen
      .getByText(tEn("signalAuditReport.entities.chipsTitle"))
      .closest("div");
    expect(entitySection).not.toBeNull();
    const scoped = within(entitySection as HTMLElement);
    expect(scoped.getByRole("button", { name: "Edit Example Brand" })).toBeInTheDocument();
    expect(scoped.getByRole("button", { name: "Edit Austin" })).toBeInTheDocument();
    expect(scoped.getByText("Example Brand")).toBeInTheDocument();
    expect(scoped.getByText("Austin")).toBeInTheDocument();
  });

  it("renders an explicit empty state when entities are missing", () => {
    render(<AuditReport report={reportWithEmptyEntitiesFixture} />);

    expect(screen.getByText(tEn("signalAuditReport.entities.chipsEmpty"))).toBeInTheDocument();
  });

  it("renders field-level certainty and evidence details for grounded claim metadata", () => {
    render(<AuditReport report={reportWithGroundingFixture} />);

    expect(screen.getByText("Integrity Review Details")).toBeInTheDocument();
    expect(screen.getByText("Integrity Review Ratio")).toBeInTheDocument();
    expect(screen.queryByText("Hallucination Risk Ratio")).not.toBeInTheDocument();
    expect(screen.getByText("Grounding Profile")).toBeInTheDocument();
    expect(screen.getByText("Dual Track V1")).toBeInTheDocument();
    expect(screen.getByText("Blocked Claim Buckets")).toBeInTheDocument();
    expect(screen.getByText(/Track B:\s+Manual Verification Required/i)).toBeInTheDocument();
    expect(screen.getByText("Prescriptive Claim Review")).toBeInTheDocument();
    expect(screen.getByText("Needs Manual Review")).toBeInTheDocument();
    expect(
      screen.getByText("Signal weak or partially contradictory; manual verification required.")
    ).toBeInTheDocument();
    expect(screen.getByText("Field-level Certainty")).toBeInTheDocument();
    expect(screen.getByText("Claims Omitted")).toBeInTheDocument();
    expect(screen.getByText("Summary")).toBeInTheDocument();
    expect(screen.getByText(/Best evidence: Source excerpt for the claim\./i)).toBeInTheDocument();
  });

  it("renders high-confidence debate metadata with semantic roles and judge summary", () => {
    render(<AuditReport report={reportWithHighConfidenceDebateFixture} />);

    fireEvent.click(screen.getByRole("button", { name: /debate process/i }));

    expect(
      screen.getByText("Assessment mode: High Confidence / Prescriptive Confidence mode")
    ).toBeInTheDocument();
    expect(screen.getByText("Delta Flow")).toBeInTheDocument();
    expect(screen.getByText("8 agents")).toBeInTheDocument();
    expect(screen.getByText("2 parallel layers")).toBeInTheDocument();
    expect(screen.getByText("Fallback judge")).toBeInTheDocument();
    expect(screen.getByText("Judge Summary")).toBeInTheDocument();
    expect(screen.getByText("Accepted: 3")).toBeInTheDocument();
    expect(screen.getByText("Downgraded: 1")).toBeInTheDocument();
    expect(screen.getByText("Rejected: 1")).toBeInTheDocument();
    expect(screen.getByText("Unresolved: 1")).toBeInTheDocument();
    expect(screen.getByText("Fallback")).toBeInTheDocument();
    expect(screen.getByText("judge_unavailable")).toBeInTheDocument();
    expect(screen.getByText("Generator")).toBeInTheDocument();
    expect(screen.getByText("Critic")).toBeInTheDocument();
    expect(screen.getByText("Judge")).toBeInTheDocument();
    expect(screen.getAllByText("smart").length).toBeGreaterThan(0);
    expect(screen.getByText("Agent Performance Breakdown")).toBeInTheDocument();
    expect(screen.getByText("SEO Generator")).toBeInTheDocument();
    expect(screen.getByText("Global Magistrate")).toBeInTheDocument();
  });
});
