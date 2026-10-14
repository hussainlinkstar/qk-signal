import React, { useState } from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import SignalUpgradeGate from "@/components/signal/SignalUpgradeGate";

const title = "See how you stack up";
const description =
  "Track your AIO and SEO scores against every competitor and get alerted when they move.";

function UpgradeGateHarness({ dismissible = true }: { dismissible?: boolean }) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Open upgrade information
      </button>
      <SignalUpgradeGate
        open={open}
        onClose={() => setOpen(false)}
        title={title}
        description={description}
        planLabel="Specialist"
        upgradeHref="/dashboard/billing?section=plans&plan=plan_specialist"
        upgradeLabel="Upgrade to Specialist"
        dismissible={dismissible}
      >
        <p>Unlimited competitor tracking</p>
      </SignalUpgradeGate>
    </>
  );
}

describe("SignalUpgradeGate accessibility", () => {
  afterEach(() => {
    document.body.style.overflow = "";
  });

  it("renders a named and described dialog with visible 44px dismissal actions", () => {
    render(<UpgradeGateHarness />);
    fireEvent.click(screen.getByRole("button", { name: "Open upgrade information" }));

    const dialog = screen.getByRole("dialog", { name: title });
    const close = within(dialog).getByRole("button", { name: /close/i });
    const notNow = within(dialog).getByRole("button", { name: "Not now" });

    expect(dialog).toHaveAccessibleDescription(description);
    expect(close).toBeVisible();
    expect(close).toHaveClass("min-h-11", "min-w-11");
    expect(notNow).toBeVisible();
    expect(notNow).toHaveClass("min-h-11");
    expect(within(dialog).getByRole("link", { name: "Upgrade to Specialist" })).toHaveAttribute(
      "href",
      "/dashboard/billing?section=plans&plan=plan_specialist"
    );
  });

  it("closes from the visible close button and restores focus to the opener", async () => {
    render(<UpgradeGateHarness />);
    const trigger = screen.getByRole("button", { name: "Open upgrade information" });
    trigger.focus();
    fireEvent.click(trigger);

    const dialog = screen.getByRole("dialog", { name: title });
    fireEvent.click(within(dialog).getByRole("button", { name: /close/i }));

    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: title })).not.toBeInTheDocument()
    );
    expect(trigger).toHaveFocus();
  });

  it("draws no offset band on the gradient action, which read as a white border", () => {
    render(<UpgradeGateHarness />);
    fireEvent.click(screen.getByRole("button", { name: "Open upgrade information" }));
    const dialog = screen.getByRole("dialog", { name: title });
    const cta = within(dialog).getByRole("link", { name: /Upgrade to/ });
    // `ring-offset-*` paints a band in the offset colour, white by default,
    // tight against the fill. The indicator itself stays.
    expect(cta.className).not.toMatch(/ring-offset/);
    expect(cta.className).toContain("focus-visible:ring-2");
    expect(
      Array.from(dialog.querySelectorAll<HTMLElement>("a, button")).filter((el) =>
        /ring-offset/.test(el.className)
      )
    ).toHaveLength(0);
  });

  it("contains focus while open and closes from the Not now action", async () => {
    render(<UpgradeGateHarness />);
    const trigger = screen.getByRole("button", { name: "Open upgrade information" });
    trigger.focus();
    fireEvent.click(trigger);

    const dialog = screen.getByRole("dialog", { name: title });
    const close = within(dialog).getByRole("button", { name: /close/i });
    const controls = Array.from(dialog.querySelectorAll<HTMLElement>("button, a[href]"));
    const lastControl = controls.at(-1);

    // Opening focuses the panel, not the first control. The first control is
    // the upgrade action, a purchase, and focusing it on mount both lands the
    // user on a payment and paints its focus ring unprompted every time the
    // gate appears, which reads as a border on the gradient fill.
    expect(dialog).toHaveFocus();
    expect(dialog).toHaveAttribute("tabindex", "-1");
    expect(lastControl).toBeDefined();
    lastControl?.focus();
    fireEvent.keyDown(lastControl as HTMLElement, { key: "Tab" });
    expect(close).toHaveFocus();

    fireEvent.click(within(dialog).getByRole("button", { name: "Not now" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: title })).not.toBeInTheDocument()
    );
    expect(trigger).toHaveFocus();
  });

  it("wraps reverse focus from the close button to the last dialog control", () => {
    render(<UpgradeGateHarness />);
    fireEvent.click(screen.getByRole("button", { name: "Open upgrade information" }));

    const dialog = screen.getByRole("dialog", { name: title });
    const close = within(dialog).getByRole("button", { name: /close/i });
    const controls = Array.from(dialog.querySelectorAll<HTMLElement>("button, a[href]"));
    const lastControl = controls.at(-1);

    expect(lastControl).toBeDefined();
    close.focus();
    fireEvent.keyDown(close, { key: "Tab", shiftKey: true });
    expect(lastControl).toHaveFocus();
  });

  it("restores the prior body scroll state after dismissal", async () => {
    document.body.style.overflow = "clip";
    render(<UpgradeGateHarness />);
    fireEvent.click(screen.getByRole("button", { name: "Open upgrade information" }));

    expect(document.body).toHaveAttribute("data-scroll-locked");
    fireEvent.click(screen.getByRole("button", { name: "Not now" }));

    await waitFor(() => expect(document.body).not.toHaveAttribute("data-scroll-locked"));
  });

  it("closes on Escape and restores focus to the opener", async () => {
    render(<UpgradeGateHarness />);
    const trigger = screen.getByRole("button", { name: "Open upgrade information" });
    trigger.focus();
    fireEvent.click(trigger);

    expect(screen.getByRole("dialog", { name: title })).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });

    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: title })).not.toBeInTheDocument()
    );
    expect(trigger).toHaveFocus();
  });
});

// Pages that blur their content while locked pass dismissible={false}, otherwise
// dismissing the gate strands the user on an unreadable, non-interactive page.
describe("SignalUpgradeGate when it cannot be dismissed", () => {
  afterEach(() => {
    document.body.style.overflow = "";
  });

  it("offers only the upgrade and fallback exits", () => {
    render(<UpgradeGateHarness dismissible={false} />);
    fireEvent.click(screen.getByRole("button", { name: "Open upgrade information" }));

    const dialog = screen.getByRole("dialog", { name: title });

    expect(within(dialog).queryByRole("button", { name: /close/i })).not.toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "Not now" })).not.toBeInTheDocument();
    expect(within(dialog).getByRole("link", { name: "Upgrade to Specialist" })).toBeVisible();
    expect(within(dialog).getByRole("link", { name: "Back to dashboard" })).toBeVisible();
  });

  it("stays open on Escape", () => {
    render(<UpgradeGateHarness dismissible={false} />);
    fireEvent.click(screen.getByRole("button", { name: "Open upgrade information" }));

    fireEvent.keyDown(document, { key: "Escape" });

    expect(screen.getByRole("dialog", { name: title })).toBeInTheDocument();
  });
});
