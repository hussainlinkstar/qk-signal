import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ScanHistoryCard, SCAN_HISTORY_ANCHOR } from "@/components/dashboard/ScanHistoryCard";
import type { ProjectAuditHistoryEntry } from "@/services/workspaceService";
import { tEn } from "@/test/i18nEn";

const fetchProjectAuditsMock = vi.fn();
const fetchAuditByIdMock = vi.fn();
const generateAuditPdfReportMock = vi.fn();
const getTokenMock = vi.fn(async () => "token");

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: tEn }),
}));

vi.mock("@/components/auth/custom-auth", () => ({
  useAuth: () => ({ getToken: getTokenMock, isSignedIn: true, isLoading: false }),
}));

vi.mock("@/services/workspaceService", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/services/workspaceService")>();
  return {
    ...original,
    fetchProjectAudits: (...args: unknown[]) => fetchProjectAuditsMock(...args),
  };
});

vi.mock("@/services/auditService", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/services/auditService")>();
  return {
    ...original,
    fetchAuditById: (...args: unknown[]) => fetchAuditByIdMock(...args),
  };
});

vi.mock("@/lib/generateAuditPdfReport", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/generateAuditPdfReport")>();
  return {
    ...original,
    generateAuditPdfReport: (...args: unknown[]) => generateAuditPdfReportMock(...args),
  };
});

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

const makeAudit = (overrides: Partial<ProjectAuditHistoryEntry>): ProjectAuditHistoryEntry => ({
  id: 1,
  project_id: 9,
  audit_type: "SMART",
  url: "https://northwind-hotels.com",
  geo_score: 62,
  seo_score: 76,
  aeo_score: 64,
  status: "completed",
  created_at: "2026-10-06T10:00:00.000Z",
  full_report: null,
  ...overrides,
});

const COMPLETED = makeAudit({ id: 903, created_at: "2026-10-06T10:00:00.000Z" });
const OLDER_COMPLETED = makeAudit({ id: 902, created_at: "2026-09-28T10:00:00.000Z" });
const FAILED = makeAudit({
  id: 900,
  status: "failed",
  seo_score: null,
  geo_score: 0,
  created_at: "2026-09-18T10:00:00.000Z",
});

const openCard = () => {
  const heading = screen.getByRole("heading", {
    name: tEn("signalScanHistory.heading"),
  });
  fireEvent.click(heading.closest("summary")!);
};

describe("ScanHistoryCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fetchProjectAuditsMock.mockResolvedValue([FAILED, OLDER_COMPLETED, COMPLETED]);
    history.replaceState(null, "", window.location.pathname);
  });

  it("lists only the requested project's audits, newest first", async () => {
    render(<ScanHistoryCard projectId="9" projectName="Northwind Hotels" />);

    await waitFor(() =>
      expect(fetchProjectAuditsMock).toHaveBeenCalledWith(
        "9",
        { Authorization: "Bearer token" },
        expect.objectContaining({ limit: 100 })
      )
    );

    openCard();
    const rows = screen.getAllByText("Smart", { selector: "small" });
    expect(rows).toHaveLength(2);
    expect(screen.getByText("6 October 2026")).toBeInTheDocument();
    expect(screen.getByText("18 September 2026")).toBeInTheDocument();
    // Newest completed scan carries the "Latest scan" marker.
    expect(screen.getByText(/Latest scan · Smart/)).toBeInTheDocument();
  });

  it("stays collapsed by default and expands on the summary toggle", async () => {
    render(<ScanHistoryCard projectId="9" />);
    await waitFor(() => expect(fetchProjectAuditsMock).toHaveBeenCalled());

    const details = document.getElementById(SCAN_HISTORY_ANCHOR)!;
    expect(details).not.toHaveAttribute("open");

    openCard();
    expect(details).toHaveAttribute("open");
  });

  it("auto-expands when opened via the #scan-history deep link", async () => {
    history.replaceState(null, "", `${window.location.pathname}#${SCAN_HISTORY_ANCHOR}`);
    render(<ScanHistoryCard projectId="9" />);
    await waitFor(() => expect(fetchProjectAuditsMock).toHaveBeenCalled());

    expect(document.getElementById(SCAN_HISTORY_ANCHOR)).toHaveAttribute("open");
  });

  it("offers a PDF download on completed scans and generates on demand", async () => {
    fetchAuditByIdMock.mockResolvedValue({
      ...COMPLETED,
      full_report: { schema_version: "2.0", scores: { seo: 76, geo: 62 } },
    });
    generateAuditPdfReportMock.mockResolvedValue(undefined);

    render(<ScanHistoryCard projectId="9" projectName="Northwind Hotels" />);
    await waitFor(() => expect(fetchProjectAuditsMock).toHaveBeenCalled());
    openCard();

    const downloads = await screen.findAllByRole("button", {
      name: tEn("signalScanHistory.downloadPdf"),
    });
    expect(downloads).toHaveLength(2);

    fireEvent.click(downloads[0]);
    await waitFor(() => expect(generateAuditPdfReportMock).toHaveBeenCalledTimes(1));
    // The report body is pulled lazily for the clicked audit only.
    expect(fetchAuditByIdMock).toHaveBeenCalledWith(903, { Authorization: "Bearer token" });
  });

  it("never offers a completed PDF on a failed scan; it offers Retry instead", async () => {
    render(<ScanHistoryCard projectId="9" />);
    await waitFor(() => expect(fetchProjectAuditsMock).toHaveBeenCalled());
    openCard();

    const failedRow = screen.getByText("18 September 2026").closest("tr")!;
    expect(failedRow.querySelector(`a[href="/dashboard/audit?projectId=9"]`)).not.toBeNull();
    expect(failedRow).toHaveTextContent(tEn("signalScanHistory.noReport"));
    expect(failedRow.querySelector("button")).toBeNull();
  });

  it("filters rows and keeps the visible count honest", async () => {
    render(<ScanHistoryCard projectId="9" />);
    await waitFor(() => expect(fetchProjectAuditsMock).toHaveBeenCalled());
    openCard();

    fireEvent.change(screen.getByLabelText(tEn("signalScanHistory.filterShow")), {
      target: { value: "failed" },
    });

    expect(screen.queryByText("6 October 2026")).not.toBeInTheDocument();
    expect(screen.getByText("18 September 2026")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Showing 1 scan");
  });

  it("surfaces a load failure instead of an empty-looking list", async () => {
    fetchProjectAuditsMock.mockRejectedValue(new Error("boom"));
    render(<ScanHistoryCard projectId="9" />);
    await waitFor(() => expect(fetchProjectAuditsMock).toHaveBeenCalled());
    openCard();

    expect(screen.getByText(tEn("signalScanHistory.loadFailed"))).toBeInTheDocument();
  });

  it("reverts to the download affordance when the export fails", async () => {
    fetchAuditByIdMock.mockRejectedValue(new Error("gone"));
    render(<ScanHistoryCard projectId="9" />);
    await waitFor(() => expect(fetchProjectAuditsMock).toHaveBeenCalled());
    openCard();

    fireEvent.click(
      (await screen.findAllByRole("button", { name: tEn("signalScanHistory.downloadPdf") }))[0]
    );
    await screen.findByText(tEn("signalScanHistory.pdfFailed"));
    expect(
      screen.getAllByRole("button", { name: tEn("signalScanHistory.downloadPdf") })
    ).toHaveLength(2);
  });
});
