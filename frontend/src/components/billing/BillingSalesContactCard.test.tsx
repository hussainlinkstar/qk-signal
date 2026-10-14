import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import "@/i18n";

import BillingSalesContactCard from "./BillingSalesContactCard";

describe("BillingSalesContactCard", () => {
  it("opens the sales dialog on the approved light panel", () => {
    render(<BillingSalesContactCard />);
    fireEvent.click(screen.getByRole("button", { name: "Contact Sales" }));

    const dialog = screen.getByRole("dialog");
    // SIGV2-1100: the old panel carried a hardcoded dark surface
    // (bg-[rgb(10,18,30)]) that rendered the light-theme fields broken.
    expect(dialog.className).not.toContain("rgb(10,18,30)");
    expect(screen.getByRole("heading", { name: "Tell us what you need" })).toBeInTheDocument();
    expect(dialog).toHaveAttribute("aria-labelledby", "sales-intake-heading");
  });

  it("focuses the first field on open", async () => {
    render(<BillingSalesContactCard />);
    fireEvent.click(screen.getByRole("button", { name: "Contact Sales" }));

    await waitFor(() => expect(screen.getByLabelText("Company name")).toHaveFocus());
  });

  it("closes on Escape and returns focus to the trigger", async () => {
    render(<BillingSalesContactCard />);
    const trigger = screen.getByRole("button", { name: "Contact Sales" });
    trigger.focus();
    fireEvent.click(trigger);
    await screen.findByRole("dialog");

    fireEvent.keyDown(document.body, { key: "Escape" });

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(trigger).toHaveFocus());
  });
});
