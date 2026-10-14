import React from "react";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import BrandVsCompetitorVisibilityChart from "@/components/dashboard/BrandVsCompetitorVisibilityChart";
import { tEn } from "@/test/i18nEn";
import type { ComparativeVisibilityResponse } from "@/types/monitoring";

const requestJson = vi.hoisted(() => vi.fn());
vi.mock("@/services/http", () => ({ requestJson }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: tEn }),
}));

const DAY = 24 * 60 * 60 * 1000;
const WEEK_SECONDS = 7 * 24 * 3600;

const isoDaysAgo = (days: number) => new Date(Date.now() - days * DAY).toISOString();

function buildPayload(
  overrides: Partial<ComparativeVisibilityResponse> = {}
): ComparativeVisibilityResponse {
  return {
    project_id: 9,
    competitors_last_measured_at: isoDaysAgo(2),
    competitor_sweep_interval_seconds: WEEK_SECONDS,
    domains: {
      "brand.example": {
        is_primary: true,
        label: "brand.example",
        providers: {
          google: { visibility_score: 72, cited_count: 4, total_checks: 5 },
        },
        trend: [{ date: "2026-10-05", scores: { google: 72 } }],
        share_of_voice: 60,
        last_measured_at: isoDaysAgo(0),
      },
      "rival.example": {
        is_primary: false,
        label: "Rival",
        providers: {
          google: { visibility_score: 41, cited_count: 2, total_checks: 5 },
        },
        trend: [{ date: "2026-10-05", scores: { google: 41 } }],
        share_of_voice: 40,
        last_measured_at: isoDaysAgo(2),
      },
    },
    ...overrides,
  };
}

beforeEach(() => {
  requestJson.mockReset();
  requestJson.mockResolvedValue(buildPayload());
});

describe("BrandVsCompetitorVisibilityChart freshness (SIGV2-1208)", () => {
  it("states when the competitor rows were last measured", async () => {
    render(<BrandVsCompetitorVisibilityChart projectId="9" />);

    const measured = await screen.findByTestId("competitor-freshness");
    expect(measured).toHaveTextContent(/Competitors last measured/i);
    // The date itself, not a bare "recently": a reader has to be able to work
    // out the age without trusting the surface.
    expect(measured).toHaveTextContent(
      new Date(isoDaysAgo(2)).toLocaleDateString("en-US", {
        month: "short",
        day: "2-digit",
        year: "numeric",
      })
    );
  });

  it("names the scheduled competitor cadence so the age has a yardstick", async () => {
    render(<BrandVsCompetitorVisibilityChart projectId="9" />);

    expect(await screen.findByTestId("competitor-cadence")).toHaveTextContent(/every 7 days/i);
  });

  it("flags a competitor figure older than its own cadence as overdue", async () => {
    requestJson.mockResolvedValue(buildPayload({ competitors_last_measured_at: isoDaysAgo(20) }));
    render(<BrandVsCompetitorVisibilityChart projectId="9" />);

    expect(await screen.findByTestId("competitor-freshness")).toHaveTextContent(/overdue/i);
  });

  it("does not call a figure overdue while it is inside the cadence", async () => {
    render(<BrandVsCompetitorVisibilityChart projectId="9" />);

    expect(await screen.findByTestId("competitor-freshness")).not.toHaveTextContent(/overdue/i);
  });

  it("says competitors refresh on demand when the plan schedules no sweep", async () => {
    requestJson.mockResolvedValue(
      buildPayload({
        competitor_sweep_interval_seconds: null,
        competitors_last_measured_at: isoDaysAgo(40),
      })
    );
    render(<BrandVsCompetitorVisibilityChart projectId="9" />);

    expect(await screen.findByTestId("competitor-cadence")).toHaveTextContent(/on demand/i);
    // With no scheduled cadence there is no interval to be overdue against.
    expect(screen.getByTestId("competitor-freshness")).not.toHaveTextContent(/overdue/i);
  });

  it("reports an unmeasured competitor as never measured rather than as zero", async () => {
    const payload = buildPayload({ competitors_last_measured_at: null });
    payload.domains["rival.example"].last_measured_at = null;
    requestJson.mockResolvedValue(payload);
    render(<BrandVsCompetitorVisibilityChart projectId="9" />);

    expect(await screen.findByTestId("competitor-freshness")).toHaveTextContent(
      /not measured yet/i
    );
    expect(screen.getByTestId("domain-measured-rival.example")).toHaveTextContent(
      /not measured yet/i
    );
  });

  it("dates each domain card, so a stale row is not read off a fresh neighbour", async () => {
    render(<BrandVsCompetitorVisibilityChart projectId="9" />);

    const brand = await screen.findByTestId("domain-measured-brand.example");
    const rival = screen.getByTestId("domain-measured-rival.example");
    expect(brand).toHaveTextContent(/Measured/i);
    expect(rival).toHaveTextContent(/Measured/i);
    expect(brand.textContent).not.toEqual(rival.textContent);
  });
});
