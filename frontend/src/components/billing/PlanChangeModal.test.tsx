import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import PlanChangeModal from "@/components/billing/PlanChangeModal";
import type { BillingPlanId } from "@/types/billing";

const getAuthHeaders = vi.fn(async () => ({ Authorization: "Bearer token-123" }));

const intervalChangePreview = {
  direction: "interval_change",
  current_billing_interval: "month",
  target_billing_interval: "year",
  current_plan: { id: "plan_specialist", name: "Specialist" },
  target_plan: { id: "plan_specialist", name: "Specialist" },
  proration_amount_usd: 120.5,
  immediate_charge: true,
  next_billing_date: "2026-09-01T12:00:00+00:00",
  feature_diff: { gained: [], lost: [] },
  scan_adjustment: {
    current_scans_per_month: 500,
    target_scans_per_month: 500,
  },
};

const downgradePreview = {
  direction: "downgrade",
  current_billing_interval: "year",
  target_billing_interval: "month",
  current_plan: { id: "plan_specialist", name: "Specialist" },
  target_plan: { id: "plan_standard", name: "Standard" },
  proration_amount_usd: null,
  immediate_charge: false,
  next_billing_date: "2026-08-15T12:00:00+00:00",
  feature_diff: { gained: [], lost: ["Advanced reporting dashboards"] },
  scan_adjustment: {
    current_scans_per_month: 500,
    target_scans_per_month: 100,
  },
};

const installFetchMock = (preview: Record<string, unknown>) =>
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url === "/api/billing/upgrade-preview") {
      return new Response(JSON.stringify(preview), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (url === "/api/billing/upgrade") {
      return new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    throw new Error(`Unexpected fetch call: ${url}`);
  });

const renderModal = (targetPlanId: BillingPlanId = "plan_specialist") =>
  render(
    <PlanChangeModal
      open
      onClose={vi.fn()}
      targetPlanId={targetPlanId}
      targetBillingInterval="year"
      getAuthHeaders={getAuthHeaders}
      onSuccess={vi.fn()}
    />
  );

afterEach(() => {
  vi.restoreAllMocks();
  getAuthHeaders.mockClear();
});

describe("PlanChangeModal billing interval contract", () => {
  it("sends the selected billing interval in preview and execute requests", async () => {
    const fetchMock = installFetchMock(intervalChangePreview);

    render(
      <PlanChangeModal
        open
        onClose={vi.fn()}
        targetPlanId="plan_specialist"
        targetBillingInterval="year"
        getAuthHeaders={getAuthHeaders}
        onSuccess={vi.fn()}
      />
    );

    await screen.findByText("Prorated charge today");

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/billing/upgrade-preview",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          target_plan: "plan_specialist",
          billing_interval: "year",
        }),
      })
    );

    fireEvent.click(screen.getByRole("button", { name: /confirm/i }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenNthCalledWith(
        2,
        "/api/billing/upgrade",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({
            target_plan: "plan_specialist",
            billing_interval: "year",
          }),
        })
      );
    });
  });

  it("renders both intervals and immediate proration copy for an interval-only change", async () => {
    installFetchMock(intervalChangePreview);

    render(
      <PlanChangeModal
        open
        onClose={vi.fn()}
        targetPlanId="plan_specialist"
        targetBillingInterval="year"
        getAuthHeaders={getAuthHeaders}
        onSuccess={vi.fn()}
      />
    );

    expect(await screen.findByText(/monthly billing/i)).toBeInTheDocument();
    expect(screen.getByText(/annual billing/i)).toBeInTheDocument();
    expect(screen.getByText("Prorated charge today")).toBeInTheDocument();
    expect(screen.getByText("$120.50")).toBeInTheDocument();
    expect(screen.getByText(/takes effect immediately/i)).toBeInTheDocument();
  });

  it("renders both intervals and the effective date for a next-period downgrade", async () => {
    installFetchMock(downgradePreview);

    render(
      <PlanChangeModal
        open
        onClose={vi.fn()}
        targetPlanId="plan_standard"
        targetBillingInterval="month"
        getAuthHeaders={getAuthHeaders}
        onSuccess={vi.fn()}
      />
    );

    expect(await screen.findByText(/annual billing/i)).toBeInTheDocument();
    expect(screen.getByText(/monthly billing/i)).toBeInTheDocument();
    expect(screen.getByText("August 15, 2026")).toBeInTheDocument();
    expect(screen.getByText(/start of your next billing period/i)).toBeInTheDocument();
    expect(screen.getByText(/current plan features will remain active until/i)).toBeInTheDocument();
  });

  it("renders a structured preview error detail message as text", async () => {
    const message = "Preview <strong>cannot be loaded</strong>.";
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: {
            code: "plan_change_preview_unavailable",
            message,
            retryable: false,
          },
        }),
        {
          status: 409,
          headers: { "Content-Type": "application/json" },
        }
      )
    );

    const { container } = render(
      <PlanChangeModal
        open
        onClose={vi.fn()}
        targetPlanId="plan_specialist"
        targetBillingInterval="year"
        getAuthHeaders={getAuthHeaders}
        onSuccess={vi.fn()}
      />
    );

    expect(await screen.findByText(message)).toBeInTheDocument();
    expect(container.querySelector("strong")).toBeNull();
    expect(screen.queryByText("[object Object]")).not.toBeInTheDocument();
  });

  it("reports a provider failure with the backend code as the reference", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: {
            code: "proration_preview_failed",
            message: "Unable to load the plan change preview. Please try again.",
          },
        }),
        { status: 502, headers: { "Content-Type": "application/json" } }
      )
    );

    renderModal();

    expect(
      await screen.findByText("Unable to load the plan change preview. Please try again.")
    ).toBeInTheDocument();
    expect(screen.getByText("Reference: 502 proration_preview_failed")).toBeInTheDocument();
  });

  /* SIGV2-1171: the behaviour SIGV2-1172 built here is kept exactly; what
     changes is that it is now the shared presentation rather than this file's
     own rose-tinted div, so every other failure surface looks the same. */
  it("renders the failure in the shared alert presentation", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: { code: "proration_preview_failed", message: "Unable to load the preview." },
        }),
        { status: 502, headers: { "Content-Type": "application/json" } }
      )
    );

    renderModal();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveAttribute("data-signal-alert", "danger");
    expect(alert).toHaveTextContent("Unable to load the preview.");
    expect(alert).toHaveTextContent("Reference: 502 proration_preview_failed");
  });

  it("reports a validation refusal distinctly from a provider failure", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: {
            code: "invalid_current_subscription",
            message: "The current subscription could not be validated for a plan change.",
          },
        }),
        { status: 409, headers: { "Content-Type": "application/json" } }
      )
    );

    renderModal();

    expect(
      await screen.findByText("The current subscription could not be validated for a plan change.")
    ).toBeInTheDocument();
    expect(screen.getByText("Reference: 409 invalid_current_subscription")).toBeInTheDocument();
    expect(screen.queryByText("Unable to load plan change preview.")).not.toBeInTheDocument();
  });

  it("reports an expired session when a 401 carries no usable detail", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({}), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      })
    );

    renderModal();

    expect(await screen.findByText(/your session has expired/i)).toBeInTheDocument();
    expect(screen.getByText("Reference: HTTP 401")).toBeInTheDocument();
    expect(screen.queryByText("Unable to load plan change preview.")).not.toBeInTheDocument();
  });

  it("reports an entitlement refusal when a 403 detail is empty", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: null }), {
        status: 403,
        headers: { "Content-Type": "application/json" },
      })
    );

    renderModal();

    expect(await screen.findByText(/not allowed to change plans/i)).toBeInTheDocument();
    expect(screen.getByText("Reference: HTTP 403")).toBeInTheDocument();
    expect(screen.queryByText("Unable to load plan change preview.")).not.toBeInTheDocument();
  });

  it("reports a provider failure when the body is not JSON at all", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("<html><body>502 Bad Gateway</body></html>", {
        status: 502,
        headers: { "Content-Type": "text/html" },
      })
    );

    renderModal();

    expect(await screen.findByText(/the billing provider did not respond/i)).toBeInTheDocument();
    expect(screen.getByText("Reference: HTTP 502")).toBeInTheDocument();
    expect(screen.queryByText("Unable to load plan change preview.")).not.toBeInTheDocument();
  });

  it("keeps the generic sentence only for a status that carries no usable detail or class", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: { code: "" } }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      })
    );

    renderModal();

    expect(await screen.findByText("Unable to load plan change preview.")).toBeInTheDocument();
    expect(screen.getByText("Reference: HTTP 400")).toBeInTheDocument();
  });

  it("reports a provider failure on the execute call instead of the generic sentence", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url === "/api/billing/upgrade-preview") {
        return new Response(JSON.stringify(intervalChangePreview), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url === "/api/billing/upgrade") {
        return new Response("gateway timeout", {
          status: 504,
          headers: { "Content-Type": "text/plain" },
        });
      }
      throw new Error(`Unexpected fetch call: ${url}`);
    });

    renderModal();

    await screen.findByText("Prorated charge today");
    fireEvent.click(screen.getByRole("button", { name: /confirm/i }));

    expect(await screen.findByText(/the billing provider did not respond/i)).toBeInTheDocument();
    expect(screen.getByText("Reference: HTTP 504")).toBeInTheDocument();
    expect(screen.queryByText("Plan change failed.")).not.toBeInTheDocument();
  });

  it("renders a structured execute error detail message as text", async () => {
    const message = "Plan change <script>failed safely</script>.";
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url === "/api/billing/upgrade-preview") {
        return new Response(JSON.stringify(intervalChangePreview), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url === "/api/billing/upgrade") {
        return new Response(
          JSON.stringify({
            detail: {
              code: "plan_change_conflict",
              message,
              current_plan: "plan_standard",
            },
          }),
          {
            status: 409,
            headers: { "Content-Type": "application/json" },
          }
        );
      }
      throw new Error(`Unexpected fetch call: ${url}`);
    });

    const { container } = render(
      <PlanChangeModal
        open
        onClose={vi.fn()}
        targetPlanId="plan_specialist"
        targetBillingInterval="year"
        getAuthHeaders={getAuthHeaders}
        onSuccess={vi.fn()}
      />
    );

    await screen.findByText("Prorated charge today");
    fireEvent.click(screen.getByRole("button", { name: /confirm/i }));

    expect(await screen.findByText(message)).toBeInTheDocument();
    expect(container.querySelector("script")).toBeNull();
    expect(screen.queryByText("[object Object]")).not.toBeInTheDocument();
  });
});
