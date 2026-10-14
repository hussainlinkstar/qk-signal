import type { AnchorHTMLAttributes } from "react";
import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import DashboardModulePage from "@/components/dashboard/DashboardModulePage";
import type { AuditResult } from "@/types/auditResult";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

vi.mock("next/link", () => ({
  default: ({ children, href, ...props }: AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

const buildAudit = (plan: string): AuditResult => ({
  schema_version: "2026-03-09",
  target: { type: "website", name: "Example", url: "https://example.com", metadata: {} },
  site: { url: "https://example.com", market: "us", language: "en" },
  seo: { onpage: 81, performance: 79, indexing: 80 },
  geo: { visibility_index: 72, citation_share: 44, brand_anchor: 38 },
  aeo: { answerability_score: 66, extractable_pages: 12 },
  entities: [],
  competitors: [],
  suggestions: [],
  scores: { seo: 81, geo: 72, aeo: 66, overall: 73 },
  metadata: {
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    plan,
    version: "2.0",
    audit_outcome: "completed",
  },
});

describe("DashboardModulePage", () => {
  it("treats plan_executive audits as eligible for reports access", () => {
    render(
      <DashboardModulePage
        feature="reports"
        moduleState={{
          audit: buildAudit("plan_executive"),
          history: [buildAudit("plan_executive")],
          isLoading: false,
          error: "",
          hasCompletedAudit: true,
        }}
      />
    );

    expect(screen.getByText("Module overview")).toBeInTheDocument();
    expect(screen.queryByText("dashboard.restricted.title")).not.toBeInTheDocument();
  });

  it("treats Executive display labels as eligible for Specialist features", () => {
    render(
      <DashboardModulePage
        feature="competitors"
        moduleState={{
          audit: buildAudit("Executive"),
          history: [buildAudit("Executive")],
          isLoading: false,
          error: "",
          hasCompletedAudit: true,
        }}
      />
    );

    expect(screen.getByText("Module overview")).toBeInTheDocument();
    expect(screen.queryByText("dashboard.restricted.title")).not.toBeInTheDocument();
  });
});
