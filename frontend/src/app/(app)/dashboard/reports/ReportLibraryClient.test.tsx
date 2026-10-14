import React from "react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ReportLibraryClient from "@/app/(app)/dashboard/reports/ReportLibraryClient";
import { PageHeaderHarness } from "@/test/pageHeaderHarness";
import { tEn } from "@/test/i18nEn";
import type { ReportLibraryItem } from "@/services/reportService";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: tEn, i18n: { language: "en" } }),
}));

const authMock = vi.hoisted(() => ({ getToken: vi.fn(async () => "token") }));

vi.mock("@/components/auth/custom-auth", () => ({
  useAuth: () => ({ getToken: authMock.getToken, isSignedIn: true, isLoading: false }),
}));

const reportServiceMock = vi.hoisted(() => ({
  fetchReportLibrary: vi.fn(),
  deleteReports: vi.fn(),
  downloadComplexReportPdfBlob: vi.fn(),
}));

vi.mock("@/services/reportService", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/reportService")>();
  return {
    ...actual,
    fetchReportLibrary: (...args: unknown[]) => reportServiceMock.fetchReportLibrary(...args),
    deleteReports: (...args: unknown[]) => reportServiceMock.deleteReports(...args),
    downloadComplexReportPdfBlob: (...args: unknown[]) =>
      reportServiceMock.downloadComplexReportPdfBlob(...args),
  };
});

const HOUR = 3600 * 1000;
const DAY = 24 * HOUR;

const makeItem = (overrides: Partial<ReportLibraryItem> = {}): ReportLibraryItem => ({
  report_id: "r-1",
  name: "Standard report - 1 Apr 2026 to 30 Jun 2026",
  report_kind: "standard",
  period_start: "2026-04-01T00:00:00.000Z",
  period_end: "2026-06-30T23:59:59.000Z",
  created_at: new Date(Date.now() - 2 * HOUR).toISOString(),
  size_bytes: 2_516_582,
  status: "succeeded",
  error: null,
  expires_at: new Date(Date.now() + 6 * DAY + HOUR).toISOString(),
  link_expired: false,
  link_expiry_days_remaining: 6,
  retention_days: 30,
  download_url: "/api/v1/reports/complex/r-1/download",
  ...overrides,
});

const expiredItem = makeItem({
  report_id: "r-expired",
  name: "Project report - all time, 28 Sep 2026",
  report_kind: "project",
  period_start: null,
  period_end: null,
  created_at: new Date(Date.now() - 7 * DAY).toISOString(),
  size_bytes: 12_288,
  status: "expired",
  expires_at: null,
  link_expired: true,
  link_expiry_days_remaining: 0,
  download_url: null,
});

const runningItem = makeItem({
  report_id: "r-running",
  name: "Standard report - all time, 5 Oct 2026",
  period_start: null,
  period_end: null,
  created_at: new Date(Date.now() - 30 * 1000).toISOString(),
  size_bytes: null,
  status: "running",
  expires_at: null,
  link_expiry_days_remaining: null,
  download_url: null,
});

const renderLibrary = () =>
  render(
    <PageHeaderHarness>
      <ReportLibraryClient />
    </PageHeaderHarness>
  );

const resolveLibrary = (items: ReportLibraryItem[]) => {
  reportServiceMock.fetchReportLibrary.mockResolvedValue({
    items,
    total: items.length,
    limit: 100,
    offset: 0,
  });
};

describe("ReportLibraryClient", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authMock.getToken.mockResolvedValue("token");
    resolveLibrary([makeItem(), expiredItem, runningItem]);
  });

  it("renders the approved page head and sub-line", async () => {
    renderLibrary();

    expect(await screen.findByRole("heading", { name: "Report library" })).toBeInTheDocument();
    expect(
      screen.getByText("Your reports, newest first. Download links show their expiry date.")
    ).toBeInTheDocument();
  });

  it("offers Standard, AIO, SEO, and Executive in the Generate report menu", async () => {
    renderLibrary();

    fireEvent.click(await screen.findByRole("button", { name: /generate report/i }));
    const menu = screen.getByRole("menu");

    expect(within(menu).getAllByRole("menuitem")).toHaveLength(7);
    expect(within(menu).getByRole("menuitem", { name: "Standard report" })).toHaveAttribute(
      "href",
      "/dashboard/reports/generate?kind=standard"
    );
    expect(within(menu).getByRole("menuitem", { name: "AIO report" })).toHaveAttribute(
      "href",
      "/dashboard/reports/generate?kind=aio"
    );
    expect(within(menu).getByRole("menuitem", { name: "SEO report" })).toHaveAttribute(
      "href",
      "/dashboard/reports/generate?kind=seo"
    );
    expect(within(menu).getByRole("menuitem", { name: "Executive report" })).toHaveAttribute(
      "href",
      "/dashboard/reports/generate?kind=executive"
    );
  });

  it("names the withheld-section behaviour in a dismissible alert", async () => {
    renderLibrary();

    expect(await screen.findByText("Inside a report")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Sections your plan does not include are marked withheld with the reason named, never silently removed."
      )
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));

    expect(screen.queryByText("Inside a report")).toBeNull();
  });

  it("renders the approved columns in order", async () => {
    renderLibrary();

    await screen.findByRole("heading", { name: "Report library" });
    const headers = screen.getAllByRole("columnheader").map((cell) => cell.textContent?.trim());

    // Leading cell is the selection checkbox column, then the approved order
    // with an unlabelled actions column last.
    expect(headers).toEqual([
      "",
      "Name",
      "Report type",
      "Period",
      "Created",
      "Size",
      "Status",
      "Link expires",
      "",
    ]);
  });

  it("serves the row cells from the listed record", async () => {
    renderLibrary();

    const row = (await screen.findByText("Standard report - 1 Apr 2026 to 30 Jun 2026")).closest(
      "tr"
    ) as HTMLElement;

    expect(within(row).getByText("standard")).toBeInTheDocument();
    // Formatted in UTC: the customer asked for an interval ending 30 June, and
    // a local-zone render would relabel it 1 July east of Greenwich.
    expect(within(row).getByText("Apr 1, 2026 to Jun 30, 2026")).toBeInTheDocument();
    expect(within(row).getByText("2h ago")).toBeInTheDocument();
    expect(within(row).getByText("2.4 MB")).toBeInTheDocument();
    expect(within(row).getByText("Ready")).toBeInTheDocument();
    expect(within(row).getByText("expires in 6 days")).toBeInTheDocument();
  });

  it("reads an absent period as all time rather than inventing one", async () => {
    renderLibrary();

    const row = (await screen.findByText("Project report - all time, 28 Sep 2026")).closest(
      "tr"
    ) as HTMLElement;

    expect(within(row).getByText("All time")).toBeInTheDocument();
  });

  it("shows an expired link as expired and refuses to offer its download", async () => {
    renderLibrary();

    const row = (await screen.findByText("Project report - all time, 28 Sep 2026")).closest(
      "tr"
    ) as HTMLElement;

    // Both the Status chip and the Link expiry cell say expired, which is the
    // point: the row is readable as dead without clicking anything.
    expect(within(row).getAllByText(/expired/i)).toHaveLength(2);
    expect(within(row).getByRole("button", { name: /download/i })).toBeDisabled();
  });

  it("disables Download on anything that has not succeeded", async () => {
    renderLibrary();

    const row = (await screen.findByText("Standard report - all time, 5 Oct 2026")).closest(
      "tr"
    ) as HTMLElement;

    expect(within(row).getByText("Generating")).toBeInTheDocument();
    expect(within(row).getByRole("button", { name: /download/i })).toBeDisabled();
  });

  it("downloads a succeeded report through the authorized endpoint", async () => {
    renderLibrary();
    reportServiceMock.downloadComplexReportPdfBlob.mockResolvedValue({
      blob: new Blob(["pdf"], { type: "application/pdf" }),
      filename: "report.pdf",
    });
    const createObjectURL = vi.fn(() => "blob:report");
    const revokeObjectURL = vi.fn();
    Object.assign(window.URL, { createObjectURL, revokeObjectURL });

    const row = (await screen.findByText("Standard report - 1 Apr 2026 to 30 Jun 2026")).closest(
      "tr"
    ) as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: /download/i }));

    await waitFor(() => {
      expect(reportServiceMock.downloadComplexReportPdfBlob).toHaveBeenCalledWith(
        "r-1",
        expect.objectContaining({ Authorization: "Bearer token" })
      );
    });
  });

  it("renders the approved empty state rather than example rows", async () => {
    resolveLibrary([]);
    renderLibrary();

    expect(
      await screen.findByText("No reports yet. Generate one from the Export menu.")
    ).toBeInTheDocument();
  });

  it("keeps Delete selected inert until something is selected", async () => {
    renderLibrary();

    expect(await screen.findByRole("button", { name: "Delete selected" })).toBeDisabled();
  });

  it("never deletes on a single click: the action is confirmed first", async () => {
    renderLibrary();

    const row = (await screen.findByText("Standard report - 1 Apr 2026 to 30 Jun 2026")).closest(
      "tr"
    ) as HTMLElement;
    fireEvent.click(within(row).getByRole("checkbox", { name: "Select row" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete selected" }));

    expect(await screen.findByText("Delete these reports?")).toBeInTheDocument();
    expect(reportServiceMock.deleteReports).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(reportServiceMock.deleteReports).not.toHaveBeenCalled();
  });

  it("deletes the selected reports once the confirmation is accepted", async () => {
    renderLibrary();
    reportServiceMock.deleteReports.mockResolvedValue({ deleted: ["r-1"], not_found: [] });

    const row = (await screen.findByText("Standard report - 1 Apr 2026 to 30 Jun 2026")).closest(
      "tr"
    ) as HTMLElement;
    fireEvent.click(within(row).getByRole("checkbox", { name: "Select row" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete selected" }));
    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));

    await waitFor(() => {
      expect(reportServiceMock.deleteReports).toHaveBeenCalledWith(
        ["r-1"],
        expect.objectContaining({ Authorization: "Bearer token" })
      );
    });
    // The list is re-read so a deleted row cannot linger on screen.
    await waitFor(() => {
      expect(reportServiceMock.fetchReportLibrary).toHaveBeenCalledTimes(2);
    });
  });

  it("selects every row through the header checkbox", async () => {
    renderLibrary();

    fireEvent.click(await screen.findByRole("checkbox", { name: "Select all rows" }));

    expect(screen.getByText("3 rows · 3 selected")).toBeInTheDocument();
  });

  it("says plainly that an unloadable library did not load", async () => {
    reportServiceMock.fetchReportLibrary.mockRejectedValue(new Error("backend unavailable"));
    renderLibrary();

    expect(await screen.findByText("backend unavailable")).toBeInTheDocument();
  });

  it("ships none of the mockup's example rows as real results", () => {
    const source = readFileSync(resolve(__dirname, "ReportLibraryClient.tsx"), "utf8");

    for (const demoRow of [
      "Q2 full audit",
      "Board pack",
      "Head-to-head vs Coastline",
      "Investor financial summary",
      "Project config snapshot",
      "Weekly digest",
      "May board pack",
      "Preview empty state",
    ]) {
      expect(source).not.toContain(demoRow);
    }
    // The mockup's build-team annotation must never reach a customer either.
    expect(source).not.toContain("@needs-backend");
  });
});
