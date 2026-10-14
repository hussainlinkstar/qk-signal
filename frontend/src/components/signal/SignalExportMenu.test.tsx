import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import SignalExportMenu from "@/components/signal/SignalExportMenu";
import {
  exportVariantsResponse,
  specialistExportVariantsResponse,
} from "@/services/__fixtures__/exportVariants";
import { tEn } from "@/test/i18nEn";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: tEn }),
}));

const { getTokenMock, reportMock } = vi.hoisted(() => ({
  getTokenMock: vi.fn(async () => "token"),
  reportMock: {
    fetchReportExportVariants: vi.fn(),
    generateComplexReportPdf: vi.fn(),
    fetchComplexReportStatus: vi.fn(),
    downloadComplexReportPdfBlob: vi.fn(),
  },
}));

vi.mock("@/components/auth/custom-auth", () => ({
  useAuth: () => ({ getToken: getTokenMock, isSignedIn: true }),
}));

vi.mock("@/components/app/WorkspaceSwitcher", () => ({
  workspaceHeaders: () => ({ "X-Workspace-Id": "1" }),
}));

vi.mock("@/services/reportService", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/reportService")>();
  return {
    ...actual,
    fetchReportExportVariants: (...args: unknown[]) =>
      reportMock.fetchReportExportVariants(...args),
    generateComplexReportPdf: (...args: unknown[]) => reportMock.generateComplexReportPdf(...args),
    fetchComplexReportStatus: (...args: unknown[]) => reportMock.fetchComplexReportStatus(...args),
    downloadComplexReportPdfBlob: (...args: unknown[]) =>
      reportMock.downloadComplexReportPdfBlob(...args),
  };
});

const queued = {
  report_id: "r1",
  status: "queued" as const,
  template_type: "Executive",
  generated_at: "",
  audit_count: 1,
  executive_summary: null,
  aggregate: null,
  download_url: null,
};

const renderMenu = async (props: Partial<React.ComponentProps<typeof SignalExportMenu>> = {}) => {
  await act(async () => {
    render(
      <SignalExportMenu page="aio" reportKind="aio" auditId={700} projectId={42} {...props} />
    );
  });
};

const openMenu = async () => {
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Export" }));
  });
};

beforeEach(() => {
  vi.clearAllMocks();
  getTokenMock.mockResolvedValue("token");
  reportMock.fetchReportExportVariants.mockResolvedValue(exportVariantsResponse());
  reportMock.generateComplexReportPdf.mockResolvedValue(queued);
  reportMock.fetchComplexReportStatus.mockResolvedValue({
    report_id: "r1",
    status: "succeeded",
    download_url: "/download",
  });
  reportMock.downloadComplexReportPdfBlob.mockResolvedValue({
    blob: new Blob(["pdf"]),
    filename: "report.pdf",
  });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("SignalExportMenu: the report kinds the product sells", () => {
  it("lists Standard, Executive, AIO and SEO with their copy", async () => {
    await renderMenu();
    await openMenu();

    expect(screen.getByText("Export report")).toBeInTheDocument();
    expect(screen.getByText("Standard report")).toBeInTheDocument();
    expect(screen.getByText("Executive report")).toBeInTheDocument();
    expect(screen.getByText("AIO report")).toBeInTheDocument();
    expect(screen.getByText("SEO report")).toBeInTheDocument();
    expect(
      screen.getByText("Your full audit: scores, what drives them, and the actions to take.")
    ).toBeInTheDocument();
    expect(
      screen.getByText("How AI answers describe you, which sources they cite, and what to fix.")
    ).toBeInTheDocument();
  });

  it("sends the chosen variant's own report kind to the enqueue endpoint", async () => {
    await renderMenu();
    await openMenu();
    await act(async () => {
      fireEvent.click(screen.getByRole("menuitem", { name: /AIO report/ }));
    });

    expect(reportMock.generateComplexReportPdf).toHaveBeenCalledWith(
      expect.objectContaining({
        audit_ids: [700],
        project_id: 42,
        template_type: "Executive",
        report_options: expect.objectContaining({
          report_type: "standard",
          report_kind: "aio",
          branding_mode: "platform",
        }),
      }),
      expect.objectContaining({ Authorization: "Bearer token" })
    );
  });
});

describe("SignalExportMenu: locks come from the plan entitlement the API serves", () => {
  it("locks a variant the backend reports as locked, and names the plan", async () => {
    await renderMenu({ page: "competitors" });
    await openMenu();

    const competitors = screen.getByRole("menuitem", {
      name: "Competitors report - Locked, Specialist",
    });
    expect(competitors).toHaveAttribute("aria-disabled", "true");
    expect(competitors).toHaveTextContent("Specialist");
  });

  it("refuses to enqueue a locked variant", async () => {
    await renderMenu({ page: "competitors" });
    await openMenu();
    await act(async () => {
      fireEvent.click(screen.getByRole("menuitem", { name: /Competitors report - Locked/ }));
    });

    expect(reportMock.generateComplexReportPdf).not.toHaveBeenCalled();
  });

  it("unlocks that same variant when the backend says the plan includes it", async () => {
    // The only thing that changed is the API's answer. There is no client-side
    // plan table for the lock to disagree with.
    reportMock.fetchReportExportVariants.mockResolvedValue(specialistExportVariantsResponse());
    await renderMenu({ page: "competitors" });
    await openMenu();

    const competitors = screen.getByRole("menuitem", { name: /Competitors report/ });
    expect(competitors).not.toHaveAttribute("aria-disabled");
    await act(async () => {
      fireEvent.click(competitors);
    });

    expect(reportMock.generateComplexReportPdf).toHaveBeenCalledWith(
      expect.objectContaining({
        report_options: expect.objectContaining({ report_kind: "competitors" }),
      }),
      expect.anything()
    );
  });

  it("offers every report kind unlocked on a plan that can export PDFs", async () => {
    // Standard, Executive, AIO and SEO ride on `has_pdf_audit_reports`, which
    // CAPABILITY_MATRIX grants to every plan including Starter, so nothing in
    // the kind rows ever locks.
    await renderMenu();
    await openMenu();

    for (const name of ["Standard report", "Executive report", "AIO report", "SEO report"]) {
      const item = screen.getByRole("menuitem", { name: new RegExp(`^${name}`) });
      expect(item).not.toHaveAttribute("aria-disabled");
      expect(item).not.toHaveTextContent("Locked");
    }
  });

  it("never routes a locked variant anywhere instead of locking it", async () => {
    // Every row is a button, so there is no second row type that can drift
    // into a link or an upgrade redirect.
    await renderMenu();
    await openMenu();

    for (const item of screen.getAllByRole("menuitem")) {
      expect(item.tagName).toBe("BUTTON");
      expect(item).not.toHaveAttribute("href");
    }
  });

  it("disables the control rather than guessing when the entitlement call fails", async () => {
    reportMock.fetchReportExportVariants.mockRejectedValue(new Error("nope"));
    await renderMenu();

    const trigger = screen.getByRole("button", { name: "Export" });
    await waitFor(() => expect(trigger).toBeDisabled());
    expect(trigger).toHaveAttribute(
      "title",
      "Export options could not be loaded. Please try again."
    );
  });

  it("disables the control when there is no audit to export", async () => {
    await renderMenu({ auditId: null });

    const trigger = screen.getByRole("button", { name: "Export" });
    expect(trigger).toBeDisabled();
    expect(trigger).toHaveAttribute("title", "Run a check before exporting a report.");
  });
});

describe("SignalExportMenu: the keyboard and ARIA contract", () => {
  it("keeps aria-haspopup and aria-expanded in sync", async () => {
    await renderMenu();
    const trigger = screen.getByRole("button", { name: "Export" });

    expect(trigger).toHaveAttribute("aria-haspopup", "menu");
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    await openMenu();
    expect(trigger).toHaveAttribute("aria-expanded", "true");

    await openMenu();
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  it("opens on ArrowDown and moves focus to the first item", async () => {
    await renderMenu();
    const trigger = screen.getByRole("button", { name: "Export" });

    await act(async () => {
      fireEvent.keyDown(trigger, { key: "ArrowDown" });
    });
    await waitFor(() => expect(trigger).toHaveAttribute("aria-expanded", "true"));
    await waitFor(() =>
      expect(document.activeElement).toBe(screen.getByRole("menuitem", { name: /Standard report/ }))
    );
  });

  it("cycles focus with ArrowDown and ArrowUp", async () => {
    await renderMenu();
    await openMenu();
    const items = screen.getAllByRole("menuitem");
    items[0].focus();

    fireEvent.keyDown(items[0], { key: "ArrowDown" });
    expect(document.activeElement).toBe(items[1]);

    fireEvent.keyDown(items[1], { key: "ArrowUp" });
    expect(document.activeElement).toBe(items[0]);

    // Wraps rather than dead-ending, as the approved wireExport does.
    fireEvent.keyDown(items[0], { key: "ArrowUp" });
    expect(document.activeElement).toBe(items[items.length - 1]);
  });

  it("closes on Escape and returns focus to the button", async () => {
    await renderMenu();
    await openMenu();
    const trigger = screen.getByRole("button", { name: "Export" });
    const items = screen.getAllByRole("menuitem");
    items[0].focus();

    await act(async () => {
      fireEvent.keyDown(items[0], { key: "Escape" });
    });

    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(document.activeElement).toBe(trigger);
  });

  it("closes on a click outside the control", async () => {
    await renderMenu();
    await openMenu();
    expect(screen.getByRole("menu")).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(document.body);
    });

    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });
});

describe("SignalExportMenu: the job panel reports the real job state", () => {
  it("shows Queued from the enqueue response, then Ready from the poll", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    await renderMenu();
    await openMenu();
    await act(async () => {
      fireEvent.click(screen.getByRole("menuitem", { name: /Standard report/ }));
    });

    expect(screen.getByRole("status")).toHaveTextContent("Queued");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2500);
    });

    expect(screen.getByRole("status")).toHaveTextContent("Ready");
    expect(screen.getByText("Your report is ready.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download PDF" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open report library" })).toHaveAttribute(
      "href",
      "/dashboard/reports"
    );
  });

  it("shows Preparing only because the backend reported running", async () => {
    // The approved mockup fakes this with a timer. Here it is the job's own
    // state, so a job that stays queued is never described as preparing.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    reportMock.fetchComplexReportStatus.mockResolvedValue({
      report_id: "r1",
      status: "running",
    });
    await renderMenu();
    await openMenu();
    await act(async () => {
      fireEvent.click(screen.getByRole("menuitem", { name: /Standard report/ }));
    });

    expect(screen.getByRole("status")).toHaveTextContent("Queued");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2500);
    });

    expect(screen.getByRole("status")).toHaveTextContent("Preparing");
    expect(screen.queryByText("Your report is ready.")).not.toBeInTheDocument();
  });

  it("stays Queued while the backend keeps saying queued", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    reportMock.fetchComplexReportStatus.mockResolvedValue({
      report_id: "r1",
      status: "queued",
    });
    await renderMenu();
    await openMenu();
    await act(async () => {
      fireEvent.click(screen.getByRole("menuitem", { name: /Standard report/ }));
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6500);
    });

    expect(screen.getByRole("status")).toHaveTextContent("Queued");
  });

  it("reports a failed job without claiming anything was charged", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    reportMock.fetchComplexReportStatus.mockResolvedValue({
      report_id: "r1",
      status: "failed",
      error: "boom",
    });
    await renderMenu();
    await openMenu();
    await act(async () => {
      fireEvent.click(screen.getByRole("menuitem", { name: /Standard report/ }));
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2500);
    });

    expect(screen.getByRole("status")).toHaveTextContent("Failed");
    expect(
      screen.getByText("We could not build your report. Nothing was charged.")
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("distinguishes an expired report from a failed build", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    reportMock.fetchComplexReportStatus.mockResolvedValue({
      report_id: "r1",
      status: "expired",
      expired: true,
    });
    await renderMenu();
    await openMenu();
    await act(async () => {
      fireEvent.click(screen.getByRole("menuitem", { name: /Standard report/ }));
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2500);
    });

    expect(
      screen.getByText("This report is no longer available to download. Generate it again.")
    ).toBeInTheDocument();
  });

  it("downloads the finished report through the download endpoint", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const createObjectURL = vi.fn(() => "blob:report");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL });

    await renderMenu();
    await openMenu();
    await act(async () => {
      fireEvent.click(screen.getByRole("menuitem", { name: /Standard report/ }));
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2500);
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Download PDF" }));
    });

    expect(reportMock.downloadComplexReportPdfBlob).toHaveBeenCalledWith(
      "r1",
      expect.objectContaining({ Authorization: "Bearer token" })
    );
    vi.unstubAllGlobals();
  });

  it("stops polling a job the customer dismissed", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    reportMock.fetchComplexReportStatus.mockResolvedValue({
      report_id: "r1",
      status: "queued",
    });
    await renderMenu();
    await openMenu();
    await act(async () => {
      fireEvent.click(screen.getByRole("menuitem", { name: /Standard report/ }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    });
    const callsAtDismiss = reportMock.fetchComplexReportStatus.mock.calls.length;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(8000);
    });

    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(reportMock.fetchComplexReportStatus.mock.calls.length).toBeLessThanOrEqual(
      callsAtDismiss + 1
    );
  });
});
