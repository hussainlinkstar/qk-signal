import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import ScanAllowanceCard from "@/components/billing/ScanAllowanceCard";
import type { UsageAnalyticsResponse } from "@/types/billing";

// ---------------------------------------------------------------------------
// SIGV2-1306. QA saw four figures on this card, no two of which agreed:
//
//   1/200 scans remaining
//   +367% vs 30-day average
//   about 1,421 days until depletion (est. 2030-09-01)
//   1/1 sites at your plan limit        (while two projects existed)
//
// Every one of them was arithmetically correct and none of them was worth
// showing. The first two are this card's; the depletion figure is the
// backend's and is covered in `test_usage_analytics.py`; the site count turned
// out to be accurate and is SIGV2-1315.
// ---------------------------------------------------------------------------

const analytics = (overrides: Partial<UsageAnalyticsResponse> = {}): UsageAnalyticsResponse =>
  ({
    scans_used: 1,
    scans_remaining: 199,
    scan_allowance: 200,
    reset_at: null,
    renewal_date: null,
    current_plan: "plan_standard",
    // A days-old account: all the usage sits inside the 7-day window, so the
    // 7-day rate is 1/7 and the 30-day rate is 1/31.
    burn_rate_7d: 0.14,
    burn_rate_30d: 0.03,
    days_until_depletion: null,
    depletion_date: null,
    will_exhaust_before_renewal: false,
    projected_overage: 0,
    projection_reason: "insufficient_history",
    observed_days: 3,
    warning: null,
    recommendation: null,
    ...overrides,
  }) as unknown as UsageAnalyticsResponse;

describe("ScanAllowanceCard, on an account with almost no history", () => {
  it("does not publish a burn comparison between two windows covering the same days", () => {
    // +367% was a property of the window sizes, not of the customer. With a
    // padded daily series, one scan three days ago gives a 7-day rate of 1/7
    // and a 30-day rate of 1/31, whose ratio is about +330% whatever the
    // usage was.
    render(<ScanAllowanceCard data={analytics()} />);

    expect(screen.queryByText(/vs 30d avg/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/%\s*vs/i)).not.toBeInTheDocument();
  });

  it("says why there is no depletion projection, rather than 'No active usage'", () => {
    // The card had one line for every absent projection, and it was the wrong
    // one here: this account had used the product, just not for long enough
    // to extrapolate from.
    render(<ScanAllowanceCard data={analytics()} />);

    expect(screen.getByText(/Needs about a week of use to project/i)).toBeInTheDocument();
    expect(screen.getByText(/3 so far/)).toBeInTheDocument();
    expect(screen.queryByText("No active usage")).not.toBeInTheDocument();
  });

  it("names an uncapped allowance as such", () => {
    render(
      <ScanAllowanceCard
        data={analytics({
          scan_allowance: null,
          projection_reason: "allowance_uncapped",
          observed_days: 30,
        })}
      />
    );

    expect(screen.getByText(/no scan cap/i)).toBeInTheDocument();
  });

  it("still shows the rates themselves, which are observations", () => {
    // Only the extrapolation was unsupportable. A reader can still see what
    // the account is actually doing.
    render(<ScanAllowanceCard data={analytics()} />);

    expect(screen.getByText("0.1/day")).toBeInTheDocument();
    expect(screen.getByText("0.0/day")).toBeInTheDocument();
  });
});

describe("ScanAllowanceCard, once there is history behind it", () => {
  const established = analytics({
    observed_days: 30,
    burn_rate_7d: 12,
    burn_rate_30d: 10,
    days_until_depletion: 16,
    depletion_date: "2026-11-01",
    projection_reason: null,
  });

  it("publishes the comparison and the projection", () => {
    render(<ScanAllowanceCard data={established} />);

    // (12 - 10) / 10 = +20%.
    expect(screen.getByText("+20% vs 30d avg")).toBeInTheDocument();
    expect(screen.getByText("Est. 2026-11-01")).toBeInTheDocument();
    expect(screen.getByText("~16")).toBeInTheDocument();
  });
});
