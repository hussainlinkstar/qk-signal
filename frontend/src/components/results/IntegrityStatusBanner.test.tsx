import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import IntegrityStatusBanner from "@/components/results/IntegrityStatusBanner";
import type { CanonicalAuditReport } from "@/lib/reportAdapters";

const buildReport = (overrides: Partial<CanonicalAuditReport> = {}): CanonicalAuditReport =>
  ({
    schema_version: "1.0",
    url: "https://example.com",
    analysis: {},
    performance: {},
    network: {},
    warnings: [],
    metadata: {},
    hallucination: {
      flagged_claims: 0,
      total_claims: 3,
      claims: [],
      high_risk_discrepancies: [],
    },
    ...overrides,
  }) as CanonicalAuditReport;

describe("IntegrityStatusBanner", () => {
  it("shows the connected-data AI disclaimer when active external sources are present", () => {
    render(
      <IntegrityStatusBanner
        report={buildReport({
          metadata: {
            has_external_data_sources: true,
            data_sources: {
              sources: [
                {
                  source_type: "google_search_console",
                  has_external_data: true,
                  is_active: true,
                },
                {
                  source_type: "google_analytics_4",
                  has_external_data: true,
                  is_active: true,
                },
              ],
            },
          },
        })}
      />
    );

    expect(
      screen.getByText("No unsupported claims flagged by automated review")
    ).toBeInTheDocument();
    expect(
      screen.getByText(/This is a risk signal, not a guarantee of factual accuracy\./i)
    ).toBeInTheDocument();
    expect(screen.getByLabelText("AI disclaimer")).toHaveTextContent(
      "connected external data from Google Search Console and Google Analytics 4"
    );
  });

  it("suppresses the connected-data disclaimer when source entries are inactive", () => {
    render(
      <IntegrityStatusBanner
        report={buildReport({
          metadata: {
            has_external_data_sources: true,
            data_sources: {
              sources: [
                {
                  source_type: "google_search_console",
                  has_external_data: true,
                  is_active: false,
                },
              ],
            },
          },
        })}
      />
    );

    expect(screen.queryByLabelText("AI disclaimer")).not.toBeInTheDocument();
  });

  it("renders integrity certificate details even when legacy hallucination data is absent", () => {
    render(
      <IntegrityStatusBanner
        report={buildReport({
          hallucination: undefined,
          integrity_certificate: {
            schema_version: "integrity-certificate-1",
            dual_track_grounding_enabled: true,
            grounding_profile: "dual_track_v1",
            summary: {
              total_claims: 5,
              track_a_total: 3,
              track_a_supported: 2,
              track_a_flagged: 1,
              track_a_omitted: 0,
              track_b_total: 2,
              track_b_supported: 1,
              track_b_flagged: 1,
              track_b_omitted: 0,
            },
            blocked_claim_buckets: [
              { track: "track_a", category: "missing_evidence", count: 1 },
              { track: "track_b", category: "generic_recommendation", count: 1 },
            ],
            degraded: true,
            degraded_reason: "track_b_judge_unavailable",
          },
        })}
        variant="detailed"
      />
    );

    expect(screen.getByText("Grounding Profile")).toBeInTheDocument();
    expect(screen.getByText("Dual Track V1")).toBeInTheDocument();
    expect(screen.getByText("Blocked Claim Buckets")).toBeInTheDocument();
    expect(screen.getByText("Missing Evidence")).toBeInTheDocument();
    expect(screen.getByText("Generic Recommendation")).toBeInTheDocument();
    expect(screen.getAllByText(/Track B Judge Unavailable/i)).toHaveLength(2);
  });

  it("renders track-aware vision overreach bucket labels without hallucination-only wording", () => {
    render(
      <IntegrityStatusBanner
        report={buildReport({
          hallucination: undefined,
          integrity_certificate: {
            schema_version: "integrity-certificate-1",
            dual_track_grounding_enabled: true,
            grounding_profile: "dual_track_v1",
            summary: {
              total_claims: 2,
              track_a_total: 0,
              track_a_supported: 0,
              track_a_flagged: 0,
              track_a_omitted: 0,
              track_b_total: 2,
              track_b_supported: 1,
              track_b_flagged: 0,
              track_b_omitted: 1,
            },
            blocked_claim_buckets: [
              { track: "track_b", category: "vision_only_overreach", count: 1 },
            ],
            degraded: false,
            degraded_reason: null,
          },
        })}
        variant="detailed"
      />
    );

    expect(screen.getByText("Blocked Claim Buckets")).toBeInTheDocument();
    expect(screen.getByText("Vision Only Overreach")).toBeInTheDocument();
    expect(screen.getAllByText("Track B").length).toBeGreaterThan(0);
  });
});
