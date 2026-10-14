import { describe, expect, it } from "vitest";

import {
  buildAuditRecordResponse,
  formatProjectAuditScore,
  resolveProjectAuditTarget,
} from "@/lib/projectAuditFeature";
import type { ProjectAuditHistoryEntry } from "@/services/workspaceService";

const baseAudit: ProjectAuditHistoryEntry = {
  id: 42,
  project_id: 7,
  audit_type: "DEEP",
  url: "https://example.com",
  audit_target_type: "website",
  target_name: null,
  target_url: "https://example.com",
  target_metadata: { region: "global" },
  geo_score: 61,
  seo_score: 78,
  aeo_score: 55,
  status: "completed",
  created_at: "2026-03-10T09:30:00Z",
  full_report: { summary: "ok" },
};

describe("projectAuditFeature", () => {
  it("formats nullable score values consistently", () => {
    expect(formatProjectAuditScore(71.8)).toBe("72");
    expect(formatProjectAuditScore(null)).toBe("--");
    expect(formatProjectAuditScore(undefined)).toBe("--");
  });

  it("builds a canonical audit record response from project history entries", () => {
    expect(buildAuditRecordResponse(baseAudit)).toEqual({
      id: 42,
      url: "https://example.com",
      audit_target_type: "website",
      target_name: null,
      target_url: "https://example.com",
      target_metadata: { region: "global" },
      geo_score: 61,
      seo_score: 78,
      aeo_score: 55,
      status: "completed",
      audit_type: "DEEP",
      created_at: "2026-03-10T09:30:00Z",
      full_report: { summary: "ok" },
    });
  });

  it("prefers report target metadata while falling back to the stored audit target", () => {
    expect(
      resolveProjectAuditTarget(baseAudit, {
        target: {
          type: "brand",
          name: "Example AI",
          url: "https://brand.example.com",
        },
      })
    ).toEqual({
      type: "brand",
      label: "Example AI",
      url: "https://brand.example.com",
    });

    expect(resolveProjectAuditTarget(baseAudit, null)).toEqual({
      type: "website",
      label: "https://example.com",
      url: "https://example.com",
    });
  });
});
