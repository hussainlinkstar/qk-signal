import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import AuditAllowanceSection from "@/components/results/AuditAllowanceSection";
import { tEn } from "@/test/i18nEn";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: tEn }),
}));

describe("AuditAllowanceSection", () => {
  it("is the approved Allowance section, including the product statement", () => {
    render(
      <AuditAllowanceSection planLabel="Executive" used={144} remaining={1856} resetAt={null} />
    );

    expect(screen.getByRole("heading", { name: "Allowance" })).toBeInTheDocument();
    expect(
      screen.getByText(
        "Audit runs count against your plan. This never surprises you at the moment of refusal."
      )
    ).toBeInTheDocument();
    expect(screen.getByText("This scan uses 1 of your remaining scans.")).toBeInTheDocument();
  });

  it("derives the monthly limit from used plus remaining and states both", () => {
    render(
      <AuditAllowanceSection planLabel="Executive" used={144} remaining={1856} resetAt={null} />
    );

    expect(screen.getByText("Executive - 2,000 scans / month")).toBeInTheDocument();
    expect(screen.getByText("1,856 left")).toBeInTheDocument();
    expect(screen.getByText("144 used")).toBeInTheDocument();
  });

  it("counts the days until the rolling window frees a scan", () => {
    const resetAt = new Date(Date.now() + 12 * 86_400_000).toISOString();
    render(
      <AuditAllowanceSection planLabel="Executive" used={144} remaining={1856} resetAt={resetAt} />
    );

    expect(screen.getByText("resets in 12 days")).toBeInTheDocument();
  });

  it("says the plan is uncapped rather than printing a limit of its own", () => {
    render(
      <AuditAllowanceSection planLabel="Executive" used={3} remaining={null} resetAt={null} />
    );

    expect(screen.getByText("Executive - unlimited scans")).toBeInTheDocument();
  });

  it("says the allowance is unknown instead of inventing a cap", () => {
    render(
      <AuditAllowanceSection
        planLabel="Executive"
        used={null}
        remaining={undefined}
        resetAt={null}
      />
    );

    expect(screen.getByText("Your plan allowance is not available right now.")).toBeInTheDocument();
  });

  it("never uses the word credit", () => {
    const { container } = render(
      <AuditAllowanceSection planLabel="Executive" used={144} remaining={1856} resetAt={null} />
    );

    expect(container.textContent).not.toMatch(/credit/i);
  });
});
