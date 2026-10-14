import React from "react";
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import BillingHistoryPage from "@/app/(app)/dashboard/billing/history/page";

const authState = {
  isSignedIn: true,
  getToken: vi.fn(async () => "token-123"),
};

vi.mock("@/components/auth/custom-auth", () => ({
  useAuth: () => authState,
}));

describe("BillingHistoryPage", () => {
  beforeEach(() => {
    authState.getToken.mockClear();
    vi.spyOn(globalThis, "fetch").mockImplementation(
      async () =>
        new Response(JSON.stringify({ invoices: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
    );
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders clean billing history copy", async () => {
    render(<BillingHistoryPage />);

    expect(await screen.findByText(/No invoices yet/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /billing history/i })).toBeInTheDocument();
    expect(screen.getByText("Back to Billing")).toBeInTheDocument();
    expect(screen.queryByText("Ledger History")).not.toBeInTheDocument();
    expect(screen.queryByText("Vault Synced")).not.toBeInTheDocument();
  });

  it("renders an invoice response with an ISO UTC date without throwing", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          invoices: [
            {
              date: "2024-05-20T12:34:56+00:00",
              amounts: {
                amount_due: 14900,
                amount_paid: 14900,
                amount_remaining: 0,
              },
              currency: "usd",
              status: "paid",
              hosted_invoice_url: "https://invoice.stripe.test/in_123",
              invoice_pdf: "https://invoice.stripe.test/in_123.pdf",
            },
          ],
          has_more: false,
          next_starting_after: null,
        }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }
      )
    );

    expect(() => render(<BillingHistoryPage />)).not.toThrow();

    expect(await screen.findByText("May 20, 2024")).toBeInTheDocument();
    expect(screen.getAllByText("$149.00")).toHaveLength(2);
    expect(screen.getByText("paid")).toBeInTheDocument();
  });
});
