import React, { useState } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import Modal from "@/components/ui/Modal";

function ModalHarness() {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Open dialog
      </button>
      <Modal open={open} onClose={() => setOpen(false)}>
        <h2>Keyboard settings</h2>
        <button type="button">Save settings</button>
        <button type="button" onClick={() => setOpen(false)}>
          Close dialog
        </button>
      </Modal>
    </>
  );
}

describe("Modal layering", () => {
  it("portals the dialog to document.body, outside the caller's stacking context", async () => {
    render(
      <div data-testid="app-tree">
        <Modal open onClose={() => {}}>
          <p>Dialog body</p>
        </Modal>
      </div>
    );

    const dialog = await screen.findByRole("dialog");
    expect(screen.getByTestId("app-tree")).not.toContainElement(dialog);
    expect(document.body).toContainElement(dialog);
  });

  it("stacks above the top bar on the shared z scale", async () => {
    render(
      <Modal open onClose={() => {}}>
        <p>Dialog body</p>
      </Modal>
    );

    const dialog = await screen.findByRole("dialog");
    expect(dialog.parentElement?.className).toContain("z-modal");
    expect(dialog.parentElement?.className).toContain("fixed inset-0");
  });

  it("re-applies the caller's signal theme on the portal wrapper", async () => {
    render(
      <div data-signal-theme>
        <Modal open onClose={() => {}}>
          <p>Dialog body</p>
        </Modal>
      </div>
    );

    const dialog = await screen.findByRole("dialog");
    expect(dialog.parentElement?.parentElement).toHaveAttribute("data-signal-theme");
  });

  it("re-applies every CSS scope hook the caller was inside", async () => {
    render(
      <div data-signal-theme className="app-shell">
        <main>
          <Modal open onClose={() => {}}>
            <p>Dialog body</p>
          </Modal>
        </main>
      </div>
    );

    const wrapper = (await screen.findByRole("dialog")).parentElement?.parentElement;
    expect(wrapper).toHaveAttribute("data-signal-theme");
    expect(wrapper).not.toHaveClass("app-shell");
    expect(wrapper?.parentElement).toHaveClass("app-shell");
    expect(wrapper?.className).toContain("font-(family-name:--body-font)");
    expect(screen.getByRole("dialog")).toHaveClass("rounded-[20px]", "px-[30px]");
  });

  it("collects scope hooks from ancestors several levels up", async () => {
    render(
      <div className="app-shell">
        <section>
          <div>
            <Modal open onClose={() => {}}>
              <p>Dialog body</p>
            </Modal>
          </div>
        </section>
      </div>
    );

    const wrapper = (await screen.findByRole("dialog")).parentElement?.parentElement;
    expect(wrapper?.parentElement).toHaveClass("app-shell");
    expect(wrapper).not.toHaveAttribute("data-signal-theme");
  });
});

describe("Modal focus management", () => {
  beforeEach(() => {
    document.body.style.overflow = "";
  });

  afterEach(() => {
    document.body.style.overflow = "";
  });

  it("preserves the accessible name supplied by the dialog title", () => {
    render(
      <Modal open onClose={() => {}} title="Set up a passkey">
        <button>Continue</button>
      </Modal>
    );
    expect(screen.getByRole("dialog", { name: "Set up a passkey" })).toBeInTheDocument();
  });

  it("moves initial focus to the first interactive control", () => {
    render(<ModalHarness />);

    fireEvent.click(screen.getByRole("button", { name: "Open dialog" }));

    expect(screen.getByRole("button", { name: "Save settings" })).toHaveFocus();
  });

  it("wraps forward Tab from the last control to the first control", () => {
    render(<ModalHarness />);
    fireEvent.click(screen.getByRole("button", { name: "Open dialog" }));

    const first = screen.getByRole("button", { name: "Save settings" });
    const last = screen.getByRole("button", { name: "Close dialog" });
    last.focus();
    fireEvent.keyDown(last, { key: "Tab" });

    expect(first).toHaveFocus();
  });

  it("wraps Shift+Tab from the first control to the last control", () => {
    render(<ModalHarness />);
    fireEvent.click(screen.getByRole("button", { name: "Open dialog" }));

    const first = screen.getByRole("button", { name: "Save settings" });
    const last = screen.getByRole("button", { name: "Close dialog" });
    first.focus();
    fireEvent.keyDown(first, { key: "Tab", shiftKey: true });

    expect(last).toHaveFocus();
  });

  it("closes on Escape and restores focus to the element that opened it", async () => {
    render(<ModalHarness />);
    const trigger = screen.getByRole("button", { name: "Open dialog" });
    trigger.focus();
    fireEvent.click(trigger);

    fireEvent.keyDown(document, { key: "Escape" });

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it("restores the prior body scroll state after closing", () => {
    document.body.style.overflow = "clip";
    render(<ModalHarness />);

    fireEvent.click(screen.getByRole("button", { name: "Open dialog" }));
    expect(document.body).toHaveAttribute("data-scroll-locked");

    fireEvent.click(screen.getByRole("button", { name: "Close dialog" }));
    expect(document.body).not.toHaveAttribute("data-scroll-locked");
  });
});
