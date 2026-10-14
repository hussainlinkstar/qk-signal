import { afterEach, describe, expect, it, vi } from "vitest";

import { generateComplexReportPdf } from "./reportService";

describe("generateComplexReportPdf", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("omits non-positive comparison competitor ranks from the forwarded payload", async () => {
    const fetchSpy = vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          report_id: "report-123",
          status: "queued",
          template_type: "Comparative",
          generated_at: "2026-03-12T00:00:00.000Z",
          audit_count: 1,
          executive_summary: null,
          aggregate: null,
          download_url: null,
        }),
        {
          status: 200,
          headers: {
            "Content-Type": "application/json",
          },
        }
      )
    );

    await generateComplexReportPdf({
      audit_ids: [301],
      project_id: 21,
      template_type: "Comparative",
      report_options: {
        mode: "individual",
        sections: ["overview", "geo"],
        report_type: "battle",
        report_kind: "competitors",
        branding_mode: "platform",
        competitor_mode: "latest",
        comparison_competitor_name: "Competitor A",
        comparison_competitor_rank: 0,
      },
    });

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [endpoint, init] = fetchSpy.mock.calls[0] ?? [];
    expect(endpoint).toBe("/api/v1/reports/generate-complex");
    expect(init).toMatchObject({
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
    });
    expect(JSON.parse(String(init?.body))).toEqual({
      audit_ids: [301],
      site_id: 21,
      template_type: "Comparative",
      report_options: {
        mode: "individual",
        sections: ["overview", "geo"],
        report_type: "battle",
        report_kind: "competitors",
        branding_mode: "platform",
        competitor_mode: "latest",
        comparison_competitor_name: "Competitor A",
      },
    });
  });
});
