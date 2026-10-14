import React from "react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import "@/i18n";

import ScanAllowanceNote from "./ScanAllowanceNote";

describe("ScanAllowanceNote", () => {
  it("states the real window with the real remaining count", () => {
    render(<ScanAllowanceNote used={1} remaining={0} resetAt="2026-11-01T00:00:00Z" />);
    expect(
      screen.getByText(/0 of 1 scans left in your current 30-day window/i)
    ).toBeInTheDocument();
    expect(screen.getByText(/next scan frees up/i)).toBeInTheDocument();
  });

  it("states the allowance when only remaining is known", () => {
    render(<ScanAllowanceNote used={null} remaining={4} resetAt={null} />);
    expect(screen.getByText(/4 scans left in your current 30-day window/i)).toBeInTheDocument();
  });

  // SIGV2-1135: the allowance is a rolling 30-day window measured from the
  // oldest counted scan (scan_allowance_service.py), not a calendar month. The
  // old copy said "this month" while the reset date beside it was derived from
  // that rolling window, so one line could visibly contradict the other.
  it("never claims the allowance is monthly", () => {
    render(<ScanAllowanceNote used={1} remaining={0} resetAt="2026-11-01T00:00:00Z" />);
    expect(document.body.textContent ?? "").not.toMatch(/this month/i);
  });

  // The service bills at job acceptance, so a failed scan is counted. On
  // Starter (max_audits: 1) that means one failure costs the whole window, and
  // a customer should not have to discover that by losing it. SIGV2-1119 owns
  // the question of refunding a failure; nothing here promises one.
  it("says that a failed scan still uses the allowance, without promising a refund", () => {
    render(<ScanAllowanceNote used={1} remaining={0} resetAt="2026-11-01T00:00:00Z" />);
    expect(screen.getByText("A scan that fails still uses one.")).toBeInTheDocument();
    expect(document.body.textContent ?? "").not.toMatch(/refund/i);
  });

  it("says unlimited when the plan has no scan cap", () => {
    render(<ScanAllowanceNote used={2} remaining={null} resetAt={null} />);
    expect(screen.getByText(/unlimited scans/i)).toBeInTheDocument();
  });

  it("renders nothing when nothing is known", () => {
    const { container } = render(<ScanAllowanceNote used={null} remaining={null} resetAt={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("the scan allowance window is stated as the backend implements it", () => {
  it("is a rolling 30-day window in the service this copy describes", () => {
    const service = readFileSync(
      resolve(process.cwd(), "../backend/services/scan_allowance_service.py"),
      "utf8"
    );

    expect(service).toContain("SCAN_ALLOWANCE_WINDOW_DAYS = 30");
    // Still true at the time of writing: a failure is not a free retry, so the
    // copy above has to say so. If this line ever stops being true, the copy
    // is the thing to change, and this assertion is the reminder.
    expect(service).toContain("a failure is not a free retry");
  });

  it("is not described as monthly in any customer-facing allowance string", () => {
    for (const locale of ["en", "ar"]) {
      const bundle = JSON.parse(
        readFileSync(resolve(process.cwd(), `src/i18n/${locale}.json`), "utf8")
      ) as Record<string, Record<string, string>>;

      expect(JSON.stringify(bundle.signalScans), locale).not.toMatch(/this month|هذا الشهر/i);
    }
  });
});
