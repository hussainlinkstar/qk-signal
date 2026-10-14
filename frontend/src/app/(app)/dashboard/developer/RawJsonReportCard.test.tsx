import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RawJsonReportCard from "@/app/(app)/dashboard/developer/RawJsonReportCard";
import { tEn } from "@/test/i18nEn";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: tEn }),
}));

const { getTokenMock, fetchWorkspaceProjectsMock, fetchProjectAuditsMock, fetchAuditByIdMock } =
  vi.hoisted(() => ({
    getTokenMock: vi.fn(async () => "token"),
    fetchWorkspaceProjectsMock: vi.fn(),
    fetchProjectAuditsMock: vi.fn(),
    fetchAuditByIdMock: vi.fn(),
  }));

vi.mock("@/components/auth/custom-auth", () => ({
  useAuth: () => ({ getToken: getTokenMock, isSignedIn: true, isLoading: false }),
}));

vi.mock("@/services/workspaceService", () => ({
  fetchWorkspaceProjects: (...args: unknown[]) => fetchWorkspaceProjectsMock(...args),
  fetchProjectAudits: (...args: unknown[]) => fetchProjectAuditsMock(...args),
}));

vi.mock("@/services/auditService", () => ({
  fetchAuditById: (...args: unknown[]) => fetchAuditByIdMock(...args),
}));

beforeEach(() => {
  vi.clearAllMocks();
  getTokenMock.mockResolvedValue("token");
  fetchWorkspaceProjectsMock.mockResolvedValue([{ id: 42 }]);
  fetchProjectAuditsMock.mockResolvedValue([
    {
      id: 700,
      url: "https://northwind-hotels.com",
      target_name: "Northwind Hotels",
      created_at: "2026-02-03T00:00:00.000Z",
    },
  ]);
  fetchAuditByIdMock.mockResolvedValue({ id: 700, full_report: { scores: { seo: 72 } } });
});

describe("Developer Hub raw JSON report", () => {
  it("is where raw JSON lives now that the invented export section is gone", async () => {
    // SIGV2-1124 removed the audit report page's "Export this report" block,
    // and the approved Export menu is PDF-only. The approved home for raw JSON
    // is this page: "consume raw JSON reports" (Signal Developer Hub.html).
    await act(async () => {
      render(<RawJsonReportCard />);
    });

    expect(screen.getByText("Raw JSON report")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download JSON" })).toBeInTheDocument();
  });

  it("lists the audits without pulling every full report down first", async () => {
    await act(async () => {
      render(<RawJsonReportCard />);
    });

    expect(fetchProjectAuditsMock).toHaveBeenCalledWith(
      42,
      expect.anything(),
      expect.objectContaining({ includeFullReport: false })
    );
    await waitFor(() =>
      expect(screen.getByRole("option", { name: /Northwind Hotels/ })).toBeInTheDocument()
    );
  });

  it("downloads the selected audit's stored report", async () => {
    const createObjectURL = vi.fn(() => "blob:json");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL });

    await act(async () => {
      render(<RawJsonReportCard />);
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Download JSON" }));
    });

    expect(fetchAuditByIdMock).toHaveBeenCalledWith(700, expect.anything());
    expect(createObjectURL).toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("says so rather than downloading an empty file when the audit stored no report", async () => {
    fetchAuditByIdMock.mockResolvedValue({ id: 700, full_report: null });

    await act(async () => {
      render(<RawJsonReportCard />);
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Download JSON" }));
    });

    expect(screen.getByRole("alert")).toHaveTextContent(
      "That audit has no stored report to download."
    );
  });

  it("offers no download when there is nothing to download", async () => {
    fetchProjectAuditsMock.mockResolvedValue([]);

    await act(async () => {
      render(<RawJsonReportCard />);
    });

    expect(screen.getByRole("button", { name: "Download JSON" })).toBeDisabled();
    expect(screen.getByRole("option", { name: "No completed audits yet" })).toBeInTheDocument();
  });
});
