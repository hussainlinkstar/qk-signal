import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import LowScanAllowanceAlert from "./LowScanAllowanceAlert";

const requestJson = vi.hoisted(() => vi.fn());
vi.mock("@/services/http", () => ({ requestJson }));

beforeEach(() => {
  requestJson.mockReset();
  requestJson.mockResolvedValue({
    show_warning: true,
    remaining: 5,
    allowance: 200,
    pct_remaining: 2.5,
    unit: "scans",
  });
});

describe("LowScanAllowanceAlert", () => {
  it("keeps the page gutter outside the styled alert", async () => {
    render(<LowScanAllowanceAlert className="px-3 md:px-8" />);
    const alert = await screen.findByRole("alert");
    // shadcn Alert primitive, brand variant: low scans is a pre-emptive
    // notice, so the surface is neutral --panel/--line with --brand accents.
    expect(alert).toHaveAttribute("data-slot", "alert");
    expect(alert.className).toContain("bg-(--panel)");
    expect(alert.className).toContain("border-(--line)");
    expect(alert.className).not.toContain("--warn");
    expect(alert.parentElement).toHaveClass("px-3", "md:px-8");
    expect(alert).not.toHaveClass("md:px-8");
    expect(screen.getByText(/You have 5 scans remaining/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View Plans" })).toHaveAttribute(
      "href",
      "/dashboard/billing"
    );
  });

  it("preserves dismissal without changing the scan count", async () => {
    render(<LowScanAllowanceAlert />);
    fireEvent.click(await screen.findByRole("button", { name: "Dismiss scan allowance alert" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(localStorage.getItem("low-scan-allowance-alert-dismissed")).not.toBeNull();
    expect(requestJson).toHaveBeenCalledTimes(1);
  });

  it("renders nothing when the backend does not request a warning", async () => {
    requestJson.mockResolvedValue({
      show_warning: false,
      remaining: 100,
      allowance: 200,
      pct_remaining: 50,
      unit: "scans",
    });
    const { container } = render(<LowScanAllowanceAlert />);
    await requestJson.mock.results[0].value;
    expect(container).toBeEmptyDOMElement();
  });
});
